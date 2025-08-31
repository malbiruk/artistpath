import React, { useState, useEffect, useRef } from "react";
import { searchArtists } from "../utils/api";

function ArtistInput({ value, onChange, placeholder }) {
  const [inputValue, setInputValue] = useState(value?.name || "");
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const debounceTimer = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    setInputValue(value?.name || "");
  }, [value]);

  useEffect(() => {
    // Don't search if we already have a selected artist with matching name
    if (value && value.name === inputValue) {
      setSuggestions([]);
      return;
    }
    
    if (inputValue.length < 2) {
      setSuggestions([]);
      return;
    }

    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    debounceTimer.current = setTimeout(async () => {
      const results = await searchArtists(inputValue);
      setSuggestions(results);
      setShowSuggestions(true);
    }, 150);

    return () => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
    };
  }, [inputValue, value]);

  const handleSelect = (artist) => {
    setInputValue(artist.name);
    onChange(artist);
    setShowSuggestions(false);
    setSuggestions([]);
    inputRef.current?.blur();
  };

  const handleKeyDown = (e) => {
    if (!showSuggestions) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) =>
        prev < suggestions.length - 1 ? prev + 1 : prev,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : -1));
    } else if (e.key === "Enter" && selectedIndex >= 0) {
      e.preventDefault();
      handleSelect(suggestions[selectedIndex]);
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  };

  return (
    <div className="artist-input-wrapper">
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={(e) => {
          const newValue = e.target.value;
          setInputValue(newValue);
          // Clear the selected artist if input is empty or doesn't match current selection
          if (!newValue.trim() || (value && newValue !== value.name)) {
            onChange(null);
          }
        }}
        onKeyDown={handleKeyDown}
        onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
        placeholder={placeholder}
        className="artist-input"
      />

      {showSuggestions && suggestions.length > 0 && (
        <div className="suggestions">
          {suggestions.map((artist, index) => (
            <div
              key={artist.id}
              className={`suggestion ${index === selectedIndex ? "selected" : ""}`}
              onClick={() => handleSelect(artist)}
              onMouseEnter={() => setSelectedIndex(index)}
            >
              {artist.name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ArtistInput;
