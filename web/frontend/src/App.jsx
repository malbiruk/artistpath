import React, { useState, useEffect } from "react";
import "./App.css";
import ArtistInput from "./components/ArtistInput";
import { exploreArtist, findEnhancedPath } from "./utils/api";

function App() {
  const [fromArtist, setFromArtist] = useState(null);
  const [toArtist, setToArtist] = useState(null);
  const [minSimilarity, setMinSimilarity] = useState(0);
  const [maxRelations, setMaxRelations] = useState(80);
  const [maxArtists, setMaxArtists] = useState(100);
  const [totalArtists, setTotalArtists] = useState(0);
  const [currentlyShown, setCurrentlyShown] = useState(0);
  const [statusInfo, setStatusInfo] = useState("connecting...");
  const [isError, setIsError] = useState(false);
  const [networkData, setNetworkData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

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
      if (!fromArtist) {
        setNetworkData(null);
        setCurrentlyShown(0);
        return;
      }

      if (fromArtist && !toArtist) {
        // Single artist - explore
        setIsLoading(true);
        setStatusInfo("exploring artist network...");
        setIsError(false);
        try {
          const data = await exploreArtist(
            fromArtist.id,
            maxArtists,
            maxRelations,
            minSimilarity
          );
          setNetworkData(data);
          setCurrentlyShown(data.nodes?.length || 0);
          setStatusInfo("");
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
            maxArtists
          );
          setNetworkData(data);
          setCurrentlyShown(data.nodes?.length || 0);
          setStatusInfo("");
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
          <h1>artistpath</h1>
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
            <div>artists displayed: {currentlyShown.toLocaleString()}</div>
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
          ) : (
            <>
              <p>network visualization</p>
              <p>rectangular nodes with d3.js force simulation</p>
            </>
          )}
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
            <label>max relations:</label>
            <input
              type="number"
              min="1"
              max="250"
              value={maxRelations}
              onChange={(e) => setMaxRelations(parseInt(e.target.value) || 1)}
              className="setting-input"
            />
          </div>

          <div className="setting">
            <label>min similarity:</label>
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={minSimilarity.toFixed(2)}
              onChange={(e) =>
                setMinSimilarity(parseFloat(e.target.value) || 0)
              }
              className="setting-input"
            />
          </div>

          <div className="setting">
            <label>max artists:</label>
            <input
              type="number"
              min="10"
              max="500"
              value={maxArtists}
              onChange={(e) => setMaxArtists(parseInt(e.target.value) || 10)}
              className="setting-input"
            />
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;
