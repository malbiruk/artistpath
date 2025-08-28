use axum::{Router, routing::get};
use std::sync::Arc;
use tower_http::cors::CorsLayer;

mod handlers;
mod models;
mod state;

use state::AppState;

#[tokio::main]
async fn main() {
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
        .route("/api/explore", get(handlers::explore_artist))
        .route("/api/stats", get(handlers::get_stats))
        .layer(CorsLayer::permissive())
        .with_state(app_state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000").await.unwrap();

    println!("Server running on http://0.0.0.0:3000");

    axum::serve(listener, app).await.unwrap();
}
