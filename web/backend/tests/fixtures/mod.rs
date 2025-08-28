use artistpath_core::Artist;
use memmap2::{Mmap, MmapOptions};
use byteorder::{LittleEndian, WriteBytesExt};
use rustc_hash::FxHashMap;
use std::io::{Seek, Write};
use std::sync::Arc;
use tempfile::NamedTempFile;
use uuid::Uuid;
use axum::{Router, routing::get};
use tower_http::cors::CorsLayer;
use artistpath_web::state::AppState;
use artistpath_web::handlers;

pub struct TestArtists {
    pub taylor: (Uuid, Artist),
    pub olivia: (Uuid, Artist),
    pub billie: (Uuid, Artist),
    pub finneas: (Uuid, Artist),
}

impl TestArtists {
    pub fn new() -> Self {
        let taylor_id = Uuid::parse_str("20244d07-534f-4eff-b4d4-930878889970").unwrap();
        let olivia_id = Uuid::parse_str("6925db17-f35e-42f3-a4eb-84ee6bf5d4b0").unwrap();
        let billie_id = Uuid::parse_str("f4abc0b5-3f7a-4eff-8f78-ac078dbce533").unwrap();
        let finneas_id = Uuid::parse_str("151cd917-1ee2-4702-859f-90899ad897f8").unwrap();

        Self {
            taylor: (
                taylor_id,
                Artist {
                    id: taylor_id,
                    name: "Taylor Swift".to_string(),
                    url: "https://www.last.fm/music/Taylor+Swift".to_string(),
                },
            ),
            olivia: (
                olivia_id,
                Artist {
                    id: olivia_id,
                    name: "Olivia Rodrigo".to_string(),
                    url: "https://www.last.fm/music/Olivia+Rodrigo".to_string(),
                },
            ),
            billie: (
                billie_id,
                Artist {
                    id: billie_id,
                    name: "Billie Eilish".to_string(),
                    url: "https://www.last.fm/music/Billie+Eilish".to_string(),
                },
            ),
            finneas: (
                finneas_id,
                Artist {
                    id: finneas_id,
                    name: "FINNEAS".to_string(),
                    url: "https://www.last.fm/music/FINNEAS".to_string(),
                },
            ),
        }
    }

    pub fn as_metadata(&self) -> FxHashMap<Uuid, Artist> {
        let mut map = FxHashMap::default();
        map.insert(self.taylor.0, Artist {
            id: self.taylor.1.id,
            name: self.taylor.1.name.clone(),
            url: self.taylor.1.url.clone(),
        });
        map.insert(self.olivia.0, Artist {
            id: self.olivia.1.id,
            name: self.olivia.1.name.clone(),
            url: self.olivia.1.url.clone(),
        });
        map.insert(self.billie.0, Artist {
            id: self.billie.1.id,
            name: self.billie.1.name.clone(),
            url: self.billie.1.url.clone(),
        });
        map.insert(self.finneas.0, Artist {
            id: self.finneas.1.id,
            name: self.finneas.1.name.clone(),
            url: self.finneas.1.url.clone(),
        });
        map
    }

    pub fn as_name_lookup(&self) -> FxHashMap<String, Uuid> {
        let mut map = FxHashMap::default();
        map.insert("taylor swift".to_string(), self.taylor.0);
        map.insert("olivia rodrigo".to_string(), self.olivia.0);
        map.insert("billie eilish".to_string(), self.billie.0);
        map.insert("finneas".to_string(), self.finneas.0);
        map
    }
}

pub fn create_test_graph() -> (NamedTempFile, FxHashMap<Uuid, u64>) {
    let mut file = NamedTempFile::new().unwrap();
    let mut index = FxHashMap::default();
    
    let artists = TestArtists::new();

    // Taylor -> Olivia (1.0)
    let taylor_position = 0;
    index.insert(artists.taylor.0, taylor_position);
    file.write_all(&artists.taylor.0.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    file.write_all(&artists.olivia.0.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(1.0).unwrap();

    // Olivia -> Billie (0.8), Taylor (1.0)
    let olivia_position = file.stream_position().unwrap();
    index.insert(artists.olivia.0, olivia_position);
    file.write_all(&artists.olivia.0.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(2).unwrap(); // 2 connections
    file.write_all(&artists.billie.0.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.8).unwrap();
    file.write_all(&artists.taylor.0.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(1.0).unwrap();

    // Billie -> FINNEAS (1.0), Olivia (0.8)
    let billie_position = file.stream_position().unwrap();
    index.insert(artists.billie.0, billie_position);
    file.write_all(&artists.billie.0.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(2).unwrap(); // 2 connections
    file.write_all(&artists.finneas.0.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(1.0).unwrap();
    file.write_all(&artists.olivia.0.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.8).unwrap();

    // FINNEAS -> Billie (1.0)
    let finneas_position = file.stream_position().unwrap();
    index.insert(artists.finneas.0, finneas_position);
    file.write_all(&artists.finneas.0.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    file.write_all(&artists.billie.0.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(1.0).unwrap();

    file.flush().unwrap();

    (file, index)
}

pub fn create_empty_mmap() -> Mmap {
    let mut file = NamedTempFile::new().unwrap();
    file.write_all(&[0; 100]).unwrap();
    file.flush().unwrap();
    
    unsafe { MmapOptions::new().map(&file).unwrap() }
}

pub async fn create_test_app_state() -> (Router, TestArtists) {
    let test_artists = TestArtists::new();
    let (graph_file, graph_index) = create_test_graph();
    
    let app_state = Arc::new(AppState {
        name_lookup: test_artists.as_name_lookup(),
        artist_metadata: test_artists.as_metadata(),
        graph_index,
        graph_mmap: unsafe { MmapOptions::new().map(graph_file.as_file()).unwrap() },
    });

    let app = Router::new()
        .route("/health", get(handlers::health_check))
        .route("/api/artists/search", get(handlers::search_artists))
        .route("/api/path", get(handlers::find_path))
        .route("/api/explore", get(handlers::explore_artist))
        .route("/api/stats", get(handlers::get_stats))
        .layer(CorsLayer::permissive())
        .with_state(app_state);

    (app, test_artists)
}