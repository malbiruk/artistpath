import React, { useState, useEffect, useRef } from "react";
import { flushSync } from "react-dom";
import "./App.css";
import ArtistInput from "./components/ArtistInput";
import NumberInput from "./components/NumberInput";
import NetworkVisualization from "./components/NetworkVisualization";
import ArtistCard from "./components/ArtistCard";
import {
  exploreArtist,
  exploreArtistReverse,
  findEnhancedPath,
  searchArtists,
  getRandomArtist,
} from "./utils/api";
import { API_BASE_URL } from "./config";

function App() {
  // Parse initial state from URL (names only)
  const getInitialStateFromURL = () => {
    const params = new URLSearchParams(window.location.search);
    return {
      fromName: params.get("from"),
      toName: params.get("to"),
      minSimilarity: parseFloat(params.get("similarity") || "0"),
      maxRelations: parseInt(params.get("relations") || "10"),
      maxArtists: parseInt(params.get("artists") || "50"),
      algorithm: params.get("algo") || "simple",
    };
  };

  const urlParams = getInitialStateFromURL();
  const [urlArtistsToLoad, setUrlArtistsToLoad] = useState({
    from: urlParams.fromName,
    to: urlParams.toName,
  });

  const [fromArtist, setFromArtist] = useState(null);
  const [toArtist, setToArtist] = useState(null);
  const [minSimilarity, setMinSimilarity] = useState(urlParams.minSimilarity);
  const [maxRelations, setMaxRelations] = useState(urlParams.maxRelations);
  const [maxArtists, setMaxArtists] = useState(urlParams.maxArtists);
  const [totalArtists, setTotalArtists] = useState(0);
  const [currentlyShown, setCurrentlyShown] = useState(0);
  const [statusInfo, setStatusInfo] = useState("connecting...");
  const [isError, setIsError] = useState(false);
  const [networkData, setNetworkData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [algorithm, setAlgorithm] = useState(urlParams.algorithm);
  const [selectedArtist, setSelectedArtist] = useState(null);
  const [isArtistCardOpen, setIsArtistCardOpen] = useState(false);
  const [isAudioPlaying, setIsAudioPlaying] = useState(false);
  const isAudioPlayingRef = useRef(false);

  const swapArtists = () => {
    const tempFrom = fromArtist;
    const tempTo = toArtist;

    // Clear both inputs first, then swap synchronously
    flushSync(() => {
      setFromArtist(null);
      setToArtist(null);
    });

    flushSync(() => {
      setFromArtist(tempTo);
      setToArtist(tempFrom);
    });
  };

  // Fetch total artists on mount
  useEffect(() => {
    fetch(`${API_BASE_URL}/stats`)
      .then((res) => res.json())
      .then((data) => {
        setTotalArtists(data.total_artists);
        setStatusInfo("");
        setIsError(false);
      })
      .catch((err) => {
        console.error("Failed to fetch stats:", err);
        setStatusInfo("ERROR: couldn't connect to backend");
        setIsError(true);
      });
  }, []);

  // Update URL when state changes
  useEffect(() => {
    updateURL();
  }, [
    fromArtist,
    toArtist,
    minSimilarity,
    maxRelations,
    maxArtists,
    algorithm,
  ]);

  // Load artists from URL names on mount
  useEffect(() => {
    const loadArtistFromName = async (name, setArtist) => {
      if (!name) return;

      try {
        const results = await searchArtists(name);
        if (results.length > 0) {
          // Take the first result (best match)
          const artist = results[0];
          setArtist({
            id: artist.id,
            name: artist.name,
            url: artist.url,
          });
        }
      } catch (error) {
        console.error(`Failed to load artist: ${name}`, error);
      }
    };

    // Only load from URL once on mount
    if (urlArtistsToLoad.from || urlArtistsToLoad.to) {
      const loadBothArtists = async () => {
        await Promise.all([
          loadArtistFromName(urlArtistsToLoad.from, setFromArtist),
          loadArtistFromName(urlArtistsToLoad.to, setToArtist),
        ]);
      };

      loadBothArtists();

      // Clear the URL artists to load so we don't keep trying
      setUrlArtistsToLoad({ from: null, to: null });
    }
  }, [urlArtistsToLoad]);

  // Helper functions
  const formatStatusMessage = (data, isPathfinding = false) => {
    const nodeCount = data.nodes?.length || 0;
    const edgeCount = data.edges?.length || 0;
    const duration = data.timing?.duration_ms || 0;
    const visited = data.timing?.visited_nodes || 0;

    if (isPathfinding) {
      return `showing ${nodeCount.toLocaleString()} artists, ${edgeCount.toLocaleString()} connections, explored ${visited.toLocaleString()} artists in ${duration.toLocaleString()}ms`;
    }
    return `showing ${nodeCount.toLocaleString()} artists, ${edgeCount.toLocaleString()} connections`;
  };

  const handleSearchSuccess = (data, isPathfinding = false) => {
    setNetworkData(data);
    setCurrentlyShown(data.nodes?.length || 0);
    setStatusInfo(formatStatusMessage(data, isPathfinding));
  };

  const handleSearchError = (errorMessage) => {
    setStatusInfo(`ERROR: ${errorMessage}`);
    setIsError(true);
  };

  const resetSearch = () => {
    setNetworkData(null);
    setCurrentlyShown(0);
    setStatusInfo("");
  };

  const handleArtistClick = (node) => {
    setSelectedArtist({ id: node.id, name: node.name });
    setIsArtistCardOpen(true);
  };

  const handleArtistCardClose = (force = false) => {
    // Don't close if audio is playing (unless forced) - use ref for immediate value
    if (isAudioPlayingRef.current && !force) {
      return;
    }
    setIsArtistCardOpen(false);
    setSelectedArtist(null);
    setIsAudioPlaying(false);
    isAudioPlayingRef.current = false; // Reset ref as well
  };

  const handleClickAway = () => {
    // Only close if no audio is playing (no force option for click-away)
    handleArtistCardClose(false);
  };

  const handlePlayingStateChange = (isPlaying) => {
    setIsAudioPlaying(isPlaying);
    isAudioPlayingRef.current = isPlaying; // Update ref immediately
  };

  const handleFromHere = (artistData) => {
    setFromArtist({
      id: artistData.id,
      name: artistData.name,
      url: artistData.url,
    });
  };

  const handleToHere = (artistData) => {
    setToArtist({
      id: artistData.id,
      name: artistData.name,
      url: artistData.url,
    });
  };

  const handleRandomToArtist = async () => {
    try {
      const randomArtist = await getRandomArtist();
      setToArtist({
        id: randomArtist.id,
        name: randomArtist.name,
        url: randomArtist.url,
      });
    } catch (error) {
      console.error("Failed to get random artist:", error);
    }
  };

  const handleRandomFromArtist = async () => {
    try {
      const randomArtist = await getRandomArtist();
      setFromArtist({
        id: randomArtist.id,
        name: randomArtist.name,
        url: randomArtist.url,
      });
    } catch (error) {
      console.error("Failed to get random artist:", error);
    }
  };

  // Update URL when state changes
  const updateURL = () => {
    const params = new URLSearchParams();

    if (fromArtist?.name) params.set("from", fromArtist.name);
    if (toArtist?.name) params.set("to", toArtist.name);
    if (minSimilarity > 0) params.set("similarity", minSimilarity.toString());
    if (maxRelations !== 10) params.set("relations", maxRelations.toString());
    if (maxArtists !== 50) params.set("artists", maxArtists.toString());
    if (algorithm !== "simple") params.set("algo", algorithm);

    const newURL = params.toString()
      ? `?${params.toString()}`
      : window.location.pathname;
    window.history.replaceState({}, "", newURL);
  };

  const renderVisualization = () => {
    // Loading state
    if (isLoading) {
      return (
        <>
          <p className="loading">
            {fromArtist && toArtist ? "finding path" : "exploring network"}
            <span className="loading-dots">
              <span className="dot-1">.</span>
              <span className="dot-2">.</span>
              <span className="dot-3">.</span>
            </span>
          </p>
        </>
      );
    }

    // No artists selected
    if (!fromArtist && !toArtist) {
      const isTouchDevice =
        "ontouchstart" in window || navigator.maxTouchPoints > 0;
      return (
        <>
          <p>enter one artist to explore their network</p>
          <p>enter two artists to find the path between them</p>
          {isTouchDevice && (
            <p className="help-message">
              <br />
              <br />
              tap an artists to see connections
              <br />
              double-tap for artist card
            </p>
          )}
        </>
      );
    }

    // Have data to show
    if (networkData?.nodes?.length > 0) {
      const nodeCount = networkData.nodes.length;
      const edgeCount = networkData.edges.length;

      // Network too large
      if (nodeCount > 500 || edgeCount > 2000) {
        return (
          <>
            <p>
              network too large to display ({nodeCount.toLocaleString()}{" "}
              artists, {edgeCount.toLocaleString()} connections)
            </p>
            <p>reduce parameters to avoid tab crash</p>
          </>
        );
      }

      // Show visualization
      return (
        <NetworkVisualization
          data={networkData}
          onArtistClick={handleArtistClick}
          onClickAway={handleClickAway}
          selectedArtistId={selectedArtist?.id}
        />
      );
    }

    // No path found between two artists
    if (fromArtist && toArtist) {
      return (
        <>
          <p>no path found between these artists</p>
          <p>try adjusting parameters - they might be too restrictive</p>
        </>
      );
    }

    // Default case (shouldn't happen)
    return null;
  };

  // Trigger exploration/pathfinding when artists change
  useEffect(() => {
    const performSearch = async () => {
      if (!fromArtist && !toArtist) {
        resetSearch();
        return;
      }

      setIsLoading(true);
      setIsError(false);

      // Convert frontend algorithm to backend algorithm
      const backendAlgorithm = algorithm === "weighted" ? "dijkstra" : "bfs";

      try {
        if (fromArtist && !toArtist) {
          // Single artist - forward exploration (from "from" field)
          const data = await exploreArtist(
            fromArtist.id,
            maxArtists,
            maxRelations,
            minSimilarity,
            backendAlgorithm,
          );
          handleSearchSuccess(data, false);
        } else if (!fromArtist && toArtist) {
          // Single artist - reverse exploration (from "to" field)
          const data = await exploreArtistReverse(
            toArtist.id,
            maxArtists,
            maxRelations,
            minSimilarity,
            backendAlgorithm,
          );
          handleSearchSuccess(data, false);
        } else if (fromArtist && toArtist) {
          // Two artists - find path
          const data = await findEnhancedPath(
            fromArtist.id,
            toArtist.id,
            minSimilarity,
            maxRelations,
            maxArtists,
            backendAlgorithm,
          );
          handleSearchSuccess(data, true);
        }
      } catch (error) {
        const errorMessage =
          fromArtist && toArtist ? "pathfinding failed" : "exploration failed";
        handleSearchError(errorMessage);
      } finally {
        setIsLoading(false);
      }
    };

    performSearch();
  }, [
    fromArtist,
    toArtist,
    minSimilarity,
    maxRelations,
    maxArtists,
    algorithm,
  ]);

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <h1>
            <a
              href="https://github.com/malbiruk/artistpath"
              target="_blank"
              rel="noopener noreferrer"
            >
              artistpath
            </a>
          </h1>
          <p>music artist connection finder</p>
        </div>

        <div className="header-center">
          <ArtistInput
            value={fromArtist}
            onChange={setFromArtist}
            placeholder="from"
            actionIcon="⚄"
            onActionClick={handleRandomFromArtist}
          />

          <button
            onClick={swapArtists}
            className="swap-button"
            title="swap artists"
          >
            ⇄
          </button>

          <ArtistInput
            value={toArtist}
            onChange={setToArtist}
            placeholder="to"
            actionIcon="⚄"
            onActionClick={handleRandomToArtist}
          />
        </div>

        <div className="header-right">
          <div className="stats">
            <div>
              data from{" "}
              <a
                href="https://www.last.fm/home"
                target="_blank"
                rel="noopener noreferrer"
              >
                Last.fm
              </a>
            </div>
            <div>artists available: {totalArtists.toLocaleString()}</div>
          </div>
        </div>
      </header>

      <main className="main">
        <div className="visualization" onClick={handleClickAway}>
          {renderVisualization()}
          <ArtistCard
            artist={selectedArtist}
            isOpen={isArtistCardOpen}
            onClose={handleArtistCardClose}
            onFromHere={handleFromHere}
            onToHere={handleToHere}
            onPlayingStateChange={handlePlayingStateChange}
          />
        </div>
      </main>

      <footer className="footer">
        <div className="footer-left">
          <span className={`status-info ${isError ? "error" : ""}`}>
            {statusInfo}
          </span>
          <div className="mobile-stats">
            <div>total artists: {totalArtists.toLocaleString()}</div>
            <div>
              data from{" "}
              <a
                href="https://www.last.fm/home"
                target="_blank"
                rel="noopener noreferrer"
              >
                Last.fm
              </a>
            </div>
          </div>
        </div>

        <div className="footer-right">
          <div className="setting">
            <label>algorithm:</label>
            <button
              onClick={() =>
                setAlgorithm(algorithm === "simple" ? "weighted" : "simple")
              }
              className="algorithm-toggle"
            >
              {algorithm}
            </button>
          </div>

          <div className="setting">
            <label>max relations:</label>
            <NumberInput
              min={1}
              max={250}
              value={maxRelations}
              onChange={(value) => setMaxRelations(value)}
              className="setting-input"
            />
          </div>

          <div className="setting">
            <label>min similarity:</label>
            <NumberInput
              min={0}
              max={1}
              step={0.01}
              decimals={2}
              value={minSimilarity}
              onChange={(value) => setMinSimilarity(value)}
              className="setting-input"
            />
          </div>

          <div className="setting">
            <label>max artists:</label>
            <NumberInput
              min={10}
              max={500}
              value={maxArtists}
              onChange={(value) => setMaxArtists(value)}
              className="setting-input"
            />
          </div>
        </div>
      </footer>

      <div className="mobile-footer-container">
        <div className="mobile-status-stats">
          <span className={`status-info ${isError ? "error" : ""}`}>
            {statusInfo}
          </span>
          <div className="mobile-stats">
            <div>total artists: {totalArtists.toLocaleString()}</div>
            <div>
              data from{" "}
              <a
                href="https://www.last.fm/home"
                target="_blank"
                rel="noopener noreferrer"
              >
                Last.fm
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
