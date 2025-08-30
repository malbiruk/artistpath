const API_BASE = "/api";

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
) {
  try {
    const params = new URLSearchParams({
      from_id: fromId,
      to_id: toId,
      min_similarity: minSimilarity,
      max_relations: maxRelations,
      budget: budget,
      algorithm: "bfs",
    });

    const response = await fetch(`${API_BASE}/enhanced_path?${params}`);
    if (!response.ok) throw new Error("Path finding failed");

    return await response.json();
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
) {
  try {
    const params = new URLSearchParams({
      artist_id: artistId,
      budget: budget,
      max_relations: maxRelations,
      min_similarity: minSimilarity,
    });

    const response = await fetch(`${API_BASE}/explore?${params}`);
    if (!response.ok) throw new Error("Exploration failed");

    return await response.json();
  } catch (error) {
    console.error("Exploration error:", error);
    throw error;
  }
}
