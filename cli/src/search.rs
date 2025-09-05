use uuid::Uuid;
use artistpath_core::string_normalization::clean_str;

use crate::args::Args;
use crate::app::{NameLookup, ArtistMetadata};

pub struct SearchRequest {
    pub from_artist: Uuid,
    pub to_artist: Uuid,
    pub from_name: String,
    pub to_name: String,
    pub search_args: Args,
}

pub struct SearchResult {
    pub path: Option<Vec<(Uuid, f32)>>,
    pub artists_visited: usize,
    pub search_duration: f64,
    pub from_name: String,
    pub to_name: String,
    pub display_options: Args,
}

pub fn find_best_artist_match(
    name: &str,
    name_lookup: &NameLookup,
    artist_metadata: &ArtistMetadata,
) -> Result<Uuid, String> {
    let lowercase_query = name.to_lowercase();
    let clean_query = clean_str(name);
    
    // Try to get all potential matches from the lookup
    if let Some(artist_ids) = name_lookup.get(&clean_query) {
        if artist_ids.is_empty() {
            return Err(format!("Artist '{}' not found in database", name));
        }
        
        // If only one match, return it
        if artist_ids.len() == 1 {
            return Ok(artist_ids[0]);
        }
        
        // Multiple matches - prioritize exact match (case-insensitive)
        for &artist_id in artist_ids {
            if let Some(artist) = artist_metadata.get(&artist_id) {
                if artist.name.to_lowercase() == lowercase_query {
                    return Ok(artist_id);
                }
            }
        }
        
        // No exact match found, return the first one
        return Ok(artist_ids[0]);
    }
    
    Err(format!("Artist '{}' not found in database", name))
}

pub fn create_search_request(
    args: Args,
    name_lookup: &NameLookup,
    artist_metadata: &ArtistMetadata,
) -> Result<SearchRequest, String> {
    let from_artist_id = find_best_artist_match(&args.artist1, name_lookup, artist_metadata)?;
    let to_artist_id = find_best_artist_match(&args.artist2, name_lookup, artist_metadata)?;

    let from_name = artist_metadata[&from_artist_id].name.clone();
    let to_name = artist_metadata[&to_artist_id].name.clone();

    Ok(SearchRequest {
        from_artist: from_artist_id,
        to_artist: to_artist_id,
        from_name,
        to_name,
        search_args: args,
    })
}