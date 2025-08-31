import React, { useState, useEffect } from "react";
import "./App.css";
import ArtistInput from "./components/ArtistInput";
import NumberInput from "./components/NumberInput";
import NetworkVisualization from "./components/NetworkVisualization";
import { exploreArtist, findEnhancedPath } from "./utils/api";

function App() {
  const [fromArtist, setFromArtist] = useState(null);
  const [toArtist, setToArtist] = useState(null);
  const [minSimilarity, setMinSimilarity] = useState(0);
  const [maxRelations, setMaxRelations] = useState(10);
  const [maxArtists, setMaxArtists] = useState(50);
  const [totalArtists, setTotalArtists] = useState(0);
  const [currentlyShown, setCurrentlyShown] = useState(0);
  const [statusInfo, setStatusInfo] = useState("connecting...");
  const [isError, setIsError] = useState(false);
  const [networkData, setNetworkData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [algorithm, setAlgorithm] = useState("simple");

  const swapArtists = () => {
    setToArtist(fromArtist);
    setFromArtist(toArtist);
  };

  // Fetch total artists on mount
  useEffect(() => {
    fetch("/api/stats")
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

  // Helper functions
  const formatStatusMessage = (data, isPathfinding = false) => {
    const nodeCount = data.nodes?.length || 0;
    const edgeCount = data.edges?.length || 0;
    const duration = data.timing?.duration_ms || 0;
    const visited = data.timing?.visited_nodes || 0;

    if (isPathfinding) {
      return `showing ${nodeCount.toLocaleString()} artists, ${edgeCount.toLocaleString()} connections, explored ${visited.toLocaleString()} artists in ${duration}ms`;
    }
    return `showing ${nodeCount.toLocaleString()} artists, ${edgeCount.toLocaleString()} connections, explored in ${duration}ms`;
  };

  const handleSearchSuccess = (data, isPathfinding = false) => {
    setNetworkData(data);
    setCurrentlyShown(data.nodes?.length || 0);
    setStatusInfo(formatStatusMessage(data, isPathfinding));
  };

  const handleSearchError = (errorMessage) => {
    setStatusInfo(errorMessage);
    setIsError(true);
  };

  const resetSearch = () => {
    setNetworkData(null);
    setCurrentlyShown(0);
    setStatusInfo("");
  };

  const renderVisualization = () => {
    // No artists selected
    if (!fromArtist && !toArtist) {
      return (
        <>
          <p>enter one artist to explore their network</p>
          <p>enter two artists to find the path between them</p>
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
              network too large to display (
              {nodeCount.toLocaleString()} artists,{" "}
              {edgeCount.toLocaleString()} connections)
            </p>
            <p>reduce parameters to avoid tab crash</p>
          </>
        );
      }
      
      // Show visualization
      return <NetworkVisualization data={networkData} />;
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

      try {
        if ((fromArtist && !toArtist) || (!fromArtist && toArtist)) {
          // Single artist - explore
          const artistToExplore = fromArtist || toArtist;
          setStatusInfo("exploring artist network...");
          
          const data = await exploreArtist(
            artistToExplore.id,
            maxArtists,
            maxRelations,
            minSimilarity,
          );
          handleSearchSuccess(data, false);
        } else if (fromArtist && toArtist) {
          // Two artists - find path
          setStatusInfo("finding path...");
          
          const data = await findEnhancedPath(
            fromArtist.id,
            toArtist.id,
            minSimilarity,
            maxRelations,
            maxArtists,
          );
          handleSearchSuccess(data, true);
        }
      } catch (error) {
        const errorMessage = fromArtist && toArtist ? "pathfinding failed" : "exploration failed";
        handleSearchError(errorMessage);
      } finally {
        setIsLoading(false);
      }
    };

    performSearch();
  }, [fromArtist, toArtist, minSimilarity, maxRelations, maxArtists]);

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
          />

          <button
            onClick={swapArtists}
            className="swap-button"
            title="Swap artists"
          >
            ⇄
          </button>

          <ArtistInput
            value={toArtist}
            onChange={setToArtist}
            placeholder="to"
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
        <div className="visualization">
          {renderVisualization()}
        </div>
      </main>

      <footer className="footer">
        <div className="footer-left">
          <span className={`status-info ${isError ? "error" : ""}`}>
            {statusInfo}
          </span>
        </div>

        <div className="footer-right">
          <div className="setting">
            <label>algorithm:</label>
            <button
              onClick={() => setAlgorithm(algorithm === "simple" ? "weighted" : "simple")}
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
    </div>
  );
}

export default App;
