use clap::Parser;

#[derive(Parser)]
#[command(name = "artistpath")]
#[command(about = "Find the shortest connection path between any two music artists")]
pub struct Args {
    /// First artist name
    pub artist1: String,

    /// Second artist name
    pub artist2: String,

    /// Only use connections with similarity >= threshold (0.0-1.0)
    #[arg(short = 'm', long, value_name = "SIMILARITY", default_value = "0.0")]
    pub min_match: f32,

    /// Limit to top N connections per artist
    #[arg(short = 't', long, value_name = "COUNT", default_value = "80")]
    pub top_related: usize,

    /// Use weighted pathfinding (considers similarity scores)
    #[arg(short, long)]
    pub weighted: bool,

    /// Hide artist URLs from output (URLs shown by default)
    #[arg(short = 'u', long)]
    pub hide_urls: bool,

    /// Show artist UUIDs in output
    #[arg(short = 'i', long)]
    pub show_ids: bool,

    /// Show similarity scores between connected artists
    #[arg(short, long)]
    pub show_similarity: bool,

    /// Disable colored output
    #[arg(long)]
    pub no_color: bool,

    /// Verbose mode - show search info and statistics
    #[arg(short, long)]
    pub verbose: bool,

    /// Quiet mode - only show the path flow
    #[arg(short, long)]
    pub quiet: bool,
}
