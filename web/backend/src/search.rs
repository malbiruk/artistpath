use crate::models::ArtistSearchResult;
use crate::state::AppState;
use artistpath_core::string_normalization::{clean_str, extract_trigrams, strip_leading_article};
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

fn filter_artists_by_query(query: &str, state: &AppState) -> Vec<ArtistSearchResult> {
    let normalized_query = clean_str(query);
    if normalized_query.is_empty() {
        return Vec::new();
    }

    // For queries ≥ 3 chars we use the trigram index to shrink the candidate
    // set from ~5M to typically a few hundred or thousand. For shorter
    // queries trigrams aren't available, so we fall back to a full scan —
    // which is the rare case (users almost always type ≥ 3 chars).
    let candidates: Box<dyn Iterator<Item = u32>> = if normalized_query.len() >= 3 {
        let trigrams: Vec<[u8; 3]> = extract_trigrams(&normalized_query).collect();
        let mut postings: Vec<&Vec<u32>> = Vec::with_capacity(trigrams.len());
        for t in &trigrams {
            match state.trigram_index.get(t) {
                Some(list) => postings.push(list),
                // A trigram absent from the index means no name contains it,
                // so no name can contain the full query.
                None => return Vec::new(),
            }
        }
        Box::new(intersect_sorted_postings(postings).into_iter())
    } else {
        Box::new(0..state.lookup_entries.len() as u32)
    };

    let mut results = Vec::new();
    let mut seen_ids: FxHashSet<uuid::Uuid> = FxHashSet::default();

    for idx in candidates {
        let (name, artist_ids) = &state.lookup_entries[idx as usize];
        // Trigram presence is necessary but not sufficient: verify with the
        // actual substring check (false positives are e.g. "abc" trigrams
        // appearing in "abXc..." style fragments interleaved across the name).
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
        let a_exact = a_lowercase == lowercase_query;
        let b_exact = b_lowercase == lowercase_query;
        match (a_exact, b_exact) {
            (true, false) => return std::cmp::Ordering::Less,
            (false, true) => return std::cmp::Ordering::Greater,
            _ => {}
        }

        // 2. Exact normalized match (e.g. "Björk" == "bjork").
        let a_exact_norm = a_normalized == normalized_query;
        let b_exact_norm = b_normalized == normalized_query;
        match (a_exact_norm, b_exact_norm) {
            (true, false) => return std::cmp::Ordering::Less,
            (false, true) => return std::cmp::Ordering::Greater,
            _ => {}
        }

        // 3. Article-stripped exact match: query "beatles" surfaces "The Beatles".
        let a_stripped = strip_leading_article(&a_normalized);
        let b_stripped = strip_leading_article(&b_normalized);
        let a_art = a_stripped == stripped_query;
        let b_art = b_stripped == stripped_query;
        match (a_art, b_art) {
            (true, false) => return std::cmp::Ordering::Less,
            (false, true) => return std::cmp::Ordering::Greater,
            _ => {}
        }

        // 4. Starts-with, then shorter name wins on the tail.
        let a_starts = a_normalized.starts_with(&normalized_query);
        let b_starts = b_normalized.starts_with(&normalized_query);
        match (a_starts, b_starts) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.name.len().cmp(&b.name.len()),
        }
    });
}
