import React, { useState, useEffect, useRef } from "react";
import { searchArtists } from "../utils/api";

function ArtistInput({
  value,
  onChange,
  placeholder,
  actionIcon,
  onActionClick,
}) {
  const [inputValue, setInputValue] = useState(value?.name || "");
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const debounceTimer = useRef(null);
  const inputRef = useRef(null);
  const abortController = useRef(null);

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

    // Cancel any pending request
    if (abortController.current) {
      abortController.current.abort();
    }

    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    debounceTimer.current = setTimeout(async () => {
      // Create new abort controller for this request
      abortController.current = new AbortController();
      
      try {
        const results = await searchArtists(inputValue, abortController.current.signal);
        
        // Only update state if request wasn't cancelled
        if (!abortController.current.signal.aborted) {
          setSuggestions(results);
          setShowSuggestions(true);
        }
      } catch (error) {
        // Don't show error if request was cancelled
        if (!abortController.current.signal.aborted) {
          console.error("Search error:", error);
          setSuggestions([]);
        }
      }
    }, 150);

    return () => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
      if (abortController.current) {
        abortController.current.abort();
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
    <div
      className="artist-input-wrapper"
      data-has-action={actionIcon ? "true" : undefined}
    >
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={(e) => {
          const newValue = e.target.value;
          setInputValue(newValue);
          // Only clear the selected artist if input is completely empty
          if (!newValue.trim()) {
            onChange(null);
          }
        }}
        onKeyDown={handleKeyDown}
        onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
        placeholder={placeholder}
        className="artist-input"
      />

      {actionIcon && (
        <button
          className="input-action-icon"
          onClick={onActionClick}
          title="random artist"
          type="button"
        >
          {actionIcon}
        </button>
      )}

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
