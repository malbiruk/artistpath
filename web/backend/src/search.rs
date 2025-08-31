use crate::models::ArtistSearchResult;
use crate::state::AppState;
use artistpath_core::{Artist, string_normalization::clean_str};
use rustc_hash::FxHashMap;
use uuid::Uuid;

pub fn search_artists_in_state(
    state: &AppState,
    query: &str,
    limit: usize,
) -> (Vec<ArtistSearchResult>, usize) {
    if query.trim().is_empty() {
        return (vec![], 0);
    }

    let mut results = filter_artists_by_query(query, &state.name_lookup, &state.artist_metadata);
    results = sort_results_by_relevance(results, query);
    results.truncate(limit);
    let count = results.len();

    (results, count)
}

pub fn filter_artists_by_query(
    query: &str,
    name_lookup: &FxHashMap<String, Uuid>,
    artist_metadata: &FxHashMap<Uuid, Artist>,
) -> Vec<ArtistSearchResult> {
    let normalized_query = clean_str(query);

    name_lookup
        .iter()
        .filter(|(normalized_name, _)| normalized_name.contains(&normalized_query))
        .filter_map(|(_, artist_id)| {
            artist_metadata
                .get(artist_id)
                .map(|artist| ArtistSearchResult {
                    id: artist.id,
                    name: artist.name.clone(),
                    url: artist.url.clone(),
                })
        })
        .collect()
}

pub fn sort_results_by_relevance(
    mut results: Vec<ArtistSearchResult>,
    query: &str,
) -> Vec<ArtistSearchResult> {
    let normalized_query = clean_str(query);

    results.sort_by(|a, b| {
        let a_normalized = clean_str(&a.name);
        let b_normalized = clean_str(&b.name);

        let a_starts = a_normalized.starts_with(&normalized_query);
        let b_starts = b_normalized.starts_with(&normalized_query);

        match (a_starts, b_starts) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.name.len().cmp(&b.name.len()),
        }
    });

    results
}
