use crate::models::ArtistSearchResult;
use crate::state::AppState;
use artistpath_core::string_normalization::{
    clean_str, extract_trigrams, is_collab_entry, strip_leading_article,
};
use rustc_hash::FxHashSet;

pub fn search_artists_in_state(
    state: &AppState,
    query: &str,
    limit: usize,
) -> (Vec<ArtistSearchResult>, usize) {
    if query.trim().is_empty() {
        return (vec![], 0);
    }

    let mut results = filter_artists_by_query(query, state);
    sort_results_by_relevance(&mut results, query);
    results.truncate(limit);
    let count = results.len();
    (results, count)
}

/// Cap on prefix matches a <3-char query collects, keeping it O(log n + cap)
/// instead of an unbounded scan.
const PREFIX_SCAN_CAP: usize = 1000;

fn filter_artists_by_query(query: &str, state: &AppState) -> Vec<ArtistSearchResult> {
    let normalized_query = clean_str(query);
    if normalized_query.is_empty() {
        return Vec::new();
    }

    // ≥3 chars use the trigram index (substring search). Shorter queries can't
    // form a trigram and instead prefix-match the name-sorted entries via binary
    // search — bounded, so a 1-2 char query can't full-scan every name (a ~25s
    // DoS lever on the full dataset).
    let candidates: Vec<u32> = if normalized_query.len() >= 3 {
        let trigrams: Vec<[u8; 3]> = extract_trigrams(&normalized_query).collect();
        let mut postings: Vec<&Vec<u32>> = Vec::with_capacity(trigrams.len());
        for t in &trigrams {
            match state.trigram_index.get(t) {
                Some(list) => postings.push(list),
                // A trigram absent from the index means no name contains it.
                None => return Vec::new(),
            }
        }
        intersect_sorted_postings(postings)
    } else {
        prefix_candidates(&normalized_query, state)
    };

    let mut results = Vec::new();
    let mut seen_ids: FxHashSet<uuid::Uuid> = FxHashSet::default();

    for idx in candidates {
        let (name, artist_ids) = &state.lookup_entries[idx as usize];
        // Trigram membership is necessary but not sufficient (e.g. "abc"
        // trigrams interleaved across the name), so verify the substring.
        // Prefix candidates already satisfy this.
        if !name.contains(&normalized_query) {
            continue;
        }
        for artist_id in artist_ids {
            if seen_ids.insert(*artist_id) {
                if let Some(artist) = state.artist_metadata.get(artist_id) {
                    results.push(ArtistSearchResult {
                        id: artist.id,
                        name: artist.name.clone(),
                        url: artist.url.clone(),
                    });
                }
            }
        }
    }

    results
}

/// Indices of name-sorted entries whose name starts with `prefix`, capped at
/// [`PREFIX_SCAN_CAP`] so a broad prefix stays bounded.
fn prefix_candidates(prefix: &str, state: &AppState) -> Vec<u32> {
    let start = state
        .lookup_entries
        .partition_point(|(name, _)| name.as_str() < prefix);

    let mut candidates = Vec::new();
    for idx in start..state.lookup_entries.len() {
        if !state.lookup_entries[idx].0.starts_with(prefix) {
            break;
        }
        candidates.push(idx as u32);
        if candidates.len() >= PREFIX_SCAN_CAP {
            break;
        }
    }
    candidates
}

/// Linear merge intersection over sorted postings lists.
fn intersect_sorted_postings(mut postings: Vec<&Vec<u32>>) -> Vec<u32> {
    if postings.is_empty() {
        return Vec::new();
    }
    // Start from the smallest list to bound work.
    postings.sort_by_key(|p| p.len());
    let mut result = postings[0].clone();
    for postings_list in &postings[1..] {
        result = intersect_two(&result, postings_list);
        if result.is_empty() {
            return result;
        }
    }
    result
}

fn intersect_two(a: &[u32], b: &[u32]) -> Vec<u32> {
    let mut result = Vec::with_capacity(a.len().min(b.len()));
    let (mut i, mut j) = (0usize, 0usize);
    while i < a.len() && j < b.len() {
        match a[i].cmp(&b[j]) {
            std::cmp::Ordering::Equal => {
                result.push(a[i]);
                i += 1;
                j += 1;
            }
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
        }
    }
    result
}

fn sort_results_by_relevance(results: &mut Vec<ArtistSearchResult>, query: &str) {
    let normalized_query = clean_str(query);
    let lowercase_query = query.to_lowercase();
    let stripped_query = strip_leading_article(&normalized_query);

    results.sort_by(|a, b| {
        let a_normalized = clean_str(&a.name);
        let b_normalized = clean_str(&b.name);
        let a_lowercase = a.name.to_lowercase();
        let b_lowercase = b.name.to_lowercase();

        // 1. Exact match (case-insensitive on the raw display name).
        //    Honored before collab demotion so a literal feat-name query
        //    still surfaces that entry first.
        let a_exact = a_lowercase == lowercase_query;
        let b_exact = b_lowercase == lowercase_query;
        match (a_exact, b_exact) {
            (true, false) => return std::cmp::Ordering::Less,
            (false, true) => return std::cmp::Ordering::Greater,
            _ => {}
        }

        // 2. Canonical entries beat collabs (feat./ft./featuring).
        let a_collab = is_collab_entry(&a_normalized);
        let b_collab = is_collab_entry(&b_normalized);
        match (a_collab, b_collab) {
            (false, true) => return std::cmp::Ordering::Less,
            (true, false) => return std::cmp::Ordering::Greater,
            _ => {}
        }

        // 3. Exact normalized match (e.g. "Björk" == "bjork").
        let a_exact_norm = a_normalized == normalized_query;
        let b_exact_norm = b_normalized == normalized_query;
        match (a_exact_norm, b_exact_norm) {
            (true, false) => return std::cmp::Ordering::Less,
            (false, true) => return std::cmp::Ordering::Greater,
            _ => {}
        }

        // 4. Article-stripped exact match: query "beatles" surfaces "The Beatles".
        let a_stripped = strip_leading_article(&a_normalized);
        let b_stripped = strip_leading_article(&b_normalized);
        let a_art = a_stripped == stripped_query;
        let b_art = b_stripped == stripped_query;
        match (a_art, b_art) {
            (true, false) => return std::cmp::Ordering::Less,
            (false, true) => return std::cmp::Ordering::Greater,
            _ => {}
        }

        // 5. Starts-with, then shorter name wins on the tail.
        let a_starts = a_normalized.starts_with(&normalized_query);
        let b_starts = b_normalized.starts_with(&normalized_query);
        match (a_starts, b_starts) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.name.len().cmp(&b.name.len()),
        }
    });
}
