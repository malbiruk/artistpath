use crate::Args;
use rustc_hash::FxHashMap;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Serialize, Deserialize)]
pub struct JsonOutput {
    pub query: JsonQuery,
    pub result: JsonResult,
    pub stats: JsonStats,
}

#[derive(Serialize, Deserialize)]
pub struct JsonQuery {
    pub from: String,
    pub to: String,
    pub options: JsonOptions,
}

#[derive(Serialize, Deserialize)]
pub struct JsonOptions {
    pub weighted: bool,
    pub min_match: f32,
    pub top_related: usize,
}

#[derive(Serialize, Deserialize)]
pub struct JsonResult {
    pub found: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<Vec<JsonArtist>>,
}

#[derive(Serialize, Deserialize)]
pub struct JsonArtist {
    pub name: String,
    pub url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub similarity_to_previous: Option<f32>,
}

#[derive(Serialize, Deserialize)]
pub struct JsonStats {
    pub search_time_ms: u64,
    pub nodes_explored: usize,
}

pub fn create_json_output(
    path: Option<Vec<(Uuid, f32)>>,
    artists_visited: usize,
    search_duration: f64,
    from_name: String,
    to_name: String,
    args: &Args,
    artist_metadata: &FxHashMap<Uuid, crate::Artist>,
) -> JsonOutput {
    let json_path = path.as_ref().map(|path| {
        path.iter()
            .enumerate()
            .map(|(i, (artist_id, similarity))| {
                let artist_info = &artist_metadata[artist_id];
                JsonArtist {
                    name: artist_info.name.clone(),
                    url: artist_info.url.clone(),
                    similarity_to_previous: if i > 0 { Some(*similarity) } else { None },
                }
            })
            .collect()
    });

    JsonOutput {
        query: JsonQuery {
            from: from_name,
            to: to_name,
            options: JsonOptions {
                weighted: args.weighted,
                min_match: args.min_match,
                top_related: args.top_related,
            },
        },
        result: JsonResult {
            found: path.is_some(),
            path: json_path,
        },
        stats: JsonStats {
            search_time_ms: (search_duration * 1000.0) as u64,
            nodes_explored: artists_visited,
        },
    }
}

pub fn print_json_output(json_output: &JsonOutput) {
    match serde_json::to_string_pretty(json_output) {
        Ok(json_string) => println!("{}", json_string),
        Err(e) => eprintln!("Error serializing to JSON: {}", e),
    }
}