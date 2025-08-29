import React, { useState } from "react";
import "./App.css";

function App() {
  const [fromArtist, setFromArtist] = useState("");
  const [toArtist, setToArtist] = useState("");
  const [minSimilarity, setMinSimilarity] = useState(0);
  const [maxRelations, setMaxRelations] = useState(80);
  const [maxArtists, setMaxArtists] = useState(100);
  const [totalArtists, setTotalArtists] = useState(0);
  const [currentlyShown, setCurrentlyShown] = useState(0);

  const swapArtists = () => {
    setToArtist(fromArtist);
    setFromArtist(toArtist);
  };

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <h1>artistpath</h1>
          <p>music artist connection finder</p>
        </div>

        <div className="header-center">
          <input
            type="text"
            placeholder="from"
            value={fromArtist}
            onChange={(e) => setFromArtist(e.target.value)}
            className="artist-input"
          />

          <button
            onClick={swapArtists}
            className="swap-button"
            title="Swap artists"
          >
            ⇄
          </button>

          <input
            type="text"
            placeholder="to"
            value={toArtist}
            onChange={(e) => setToArtist(e.target.value)}
            className="artist-input"
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
          <span className="status-info">initializing...</span>
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
