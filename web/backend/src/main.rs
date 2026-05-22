use axum::{Router, middleware, routing::get};
use axum::http::{Request, header};
use axum::response::Response;
use std::sync::Arc;
use tower_http::cors::CorsLayer;

mod cache;
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

async fn cache_control_middleware(req: Request<axum::body::Body>, next: middleware::Next) -> Response {
    let path = req.uri().path().to_owned();
    let mut response = next.run(req).await;

    let cache_value = if path == "/api/artist/random" || path == "/health" {
        "no-cache, no-store"
    } else if path == "/api/stats" {
        "public, max-age=86400"
    } else if path.starts_with("/api/") {
        "public, max-age=86400"
    } else {
        return response;
    };

    response.headers_mut().insert(
        header::CACHE_CONTROL,
        cache_value.parse().unwrap(),
    );
    response
}

#[tokio::main]
async fn main() {
    dotenvy::from_filename("../../.env")
        .or_else(|_| dotenvy::dotenv())
        .ok();

    let app_state = match AppState::new().await {
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
        .route("/api/explore_reverse", get(handlers::explore_artist_reverse))
        .route("/api/stats", get(handlers::get_stats))
        .route("/api/artist/random", get(handlers::get_random_artist))
        .route("/api/artist/:id", get(handlers::get_artist_details))
        .layer(middleware::from_fn(cache_control_middleware))
        .layer(CorsLayer::permissive())
        .with_state(app_state);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3050").await.unwrap();

    println!("Server running on http://0.0.0.0:3050");

    axum::serve(listener, app).await.unwrap();
}
