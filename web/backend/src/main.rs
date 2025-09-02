use axum::{Router, routing::get};
use std::sync::Arc;
use tower_http::cors::CorsLayer;

mod enhanced_pathfinding;
mod exploration;
mod handlers;
mod itunes;
mod lastfm;
mod models;
mod pathfinding;
mod search;
mod state;

use state::AppState;

#[tokio::main]
async fn main() {
    // Load environment variables from .env file (try root level first)
    dotenvy::from_filename("../../.env")
        .or_else(|_| dotenvy::dotenv())
        .ok();

    let app_state = match AppState::new() {
        Ok(state) => Arc::new(state),
        Err(e) => {
            eprintln!("Failed to initialize app state: {}", e);
            std::process::exit(1);
        }
    };

    let app = Router::new()
        .route("/health", get(handlers::health_check))
        .route("/api/artists/search", get(handlers::search_artists))
        .route("/api/path", get(handlers::find_path))
        .route("/api/enhanced_path", get(handlers::find_enhanced_path))
        .route("/api/explore", get(handlers::explore_artist))
        .route("/api/stats", get(handlers::get_stats))
        .route("/api/artist/random", get(handlers::get_random_artist))
        .route("/api/artist/:id", get(handlers::get_artist_details))
        .layer(CorsLayer::permissive())
        .with_state(app_state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3050").await.unwrap();

    println!("Server running on http://0.0.0.0:3050");

    axum::serve(listener, app).await.unwrap();
}
