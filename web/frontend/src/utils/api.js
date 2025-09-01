import { API_BASE_URL } from "../config";

const API_BASE = API_BASE_URL;

export async function searchArtists(query) {
  if (!query || query.length < 2) return [];

  try {
    const response = await fetch(
      `${API_BASE}/artists/search?q=${encodeURIComponent(query)}&limit=5`,
    );
    if (!response.ok) throw new Error("Search failed");

    const data = await response.json();
    return data.results || [];
  } catch (error) {
    console.error("Search error:", error);
    return [];
  }
}

export async function findEnhancedPath(
  fromId,
  toId,
  minSimilarity,
  maxRelations,
  budget,
  algorithm = "bfs",
) {
  try {
    const params = new URLSearchParams({
      from_id: fromId,
      to_id: toId,
      min_similarity: minSimilarity,
      max_relations: maxRelations,
      budget: budget,
      algorithm: algorithm,
    });

    const url = `${API_BASE}/enhanced_path?${params}`;

    const response = await fetch(url);

    if (!response.ok)
      throw new Error(`Path finding failed: ${response.status}`);

    const response_data = await response.json();

    // Handle case where no path is found
    if (!response_data.data) {
      console.log("No path found - response_data.data is null");
      return {
        nodes: [],
        edges: [],
        path: null,
        timing: {
          duration_ms: response_data.search_stats?.duration_ms || 0,
          visited_nodes: response_data.search_stats?.artists_visited || 0,
        },
      };
    }

    // Extract the actual data from the nested structure
    return {
      nodes: response_data.data.nodes,
      edges: response_data.data.edges,
      path: response_data.data.primary_path,
      timing: {
        duration_ms: response_data.search_stats.duration_ms,
        visited_nodes: response_data.search_stats.artists_visited,
      },
    };
  } catch (error) {
    console.error("Path finding error:", error);
    throw error;
  }
}

export async function exploreArtist(
  artistId,
  budget,
  maxRelations,
  minSimilarity,
  algorithm = "bfs",
) {
  try {
    const params = new URLSearchParams({
      artist_id: artistId,
      budget: budget,
      max_relations: maxRelations,
      min_similarity: minSimilarity,
      algorithm: algorithm,
    });

    const response = await fetch(`${API_BASE}/explore?${params}`);
    if (!response.ok) throw new Error("Exploration failed");

    return await response.json();
  } catch (error) {
    console.error("Exploration error:", error);
    throw error;
  }
}
