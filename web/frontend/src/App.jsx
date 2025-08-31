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

  // Trigger exploration/pathfinding when artists change
  useEffect(() => {
    const performSearch = async () => {
      if (!fromArtist && !toArtist) {
        setNetworkData(null);
        setCurrentlyShown(0);
        setStatusInfo("");
        return;
      }

      if ((fromArtist && !toArtist) || (!fromArtist && toArtist)) {
        // Single artist - explore
        const artistToExplore = fromArtist || toArtist;
        setIsLoading(true);
        setStatusInfo("exploring artist network...");
        setIsError(false);
        try {
          const data = await exploreArtist(
            artistToExplore.id,
            maxArtists,
            maxRelations,
            minSimilarity,
          );
          setNetworkData(data);
          setCurrentlyShown(data.nodes?.length || 0);

          const nodeCount = data.nodes?.length || 0;
          const edgeCount = data.edges?.length || 0;
          const duration = data.timing?.duration_ms || 0;
          const visited = data.timing?.visited_nodes || 0;

          setStatusInfo(
            `showing ${nodeCount.toLocaleString()} artists, ${edgeCount.toLocaleString()} connections, explored in ${duration}ms`,
          );
        } catch (error) {
          setStatusInfo("exploration failed");
          setIsError(true);
        } finally {
          setIsLoading(false);
        }
      } else if (fromArtist && toArtist) {
        // Two artists - find path
        setIsLoading(true);
        setStatusInfo("finding path...");
        setIsError(false);
        try {
          const data = await findEnhancedPath(
            fromArtist.id,
            toArtist.id,
            minSimilarity,
            maxRelations,
            maxArtists,
          );
          setNetworkData(data);
          setCurrentlyShown(data.nodes?.length || 0);

          const nodeCount = data.nodes?.length || 0;
          const edgeCount = data.edges?.length || 0;
          const pathLength = data.path?.length || 0;
          const duration = data.timing?.duration_ms || 0;
          const visited = data.timing?.visited_nodes || 0;

          setStatusInfo(
            `showing ${nodeCount.toLocaleString()} artists, ${edgeCount.toLocaleString()} connections, explored ${visited.toLocaleString()} artists in ${duration}ms`,
          );
        } catch (error) {
          setStatusInfo("pathfinding failed");
          setIsError(true);
        } finally {
          setIsLoading(false);
        }
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
          {!fromArtist && !toArtist ? (
            <>
              <p>enter one artist to explore their network</p>
              <p>enter two artists to find the path between them</p>
            </>
          ) : networkData &&
            networkData.nodes &&
            networkData.nodes.length > 0 ? (
            networkData.nodes.length > 500 ||
            networkData.edges.length > 2000 ? (
              <>
                <p>
                  network too large to display (
                  {networkData.nodes.length.toLocaleString()} artists,{" "}
                  {networkData.edges.length.toLocaleString()} connections)
                </p>
                <p>reduce parameters to avoid tab crash</p>
              </>
            ) : (
              <NetworkVisualization data={networkData} />
            )
          ) : fromArtist && toArtist ? (
            <>
              <p>no path found between these artists</p>
              <p>try adjusting parameters - they might be too restrictive</p>
            </>
          ) : null}
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
