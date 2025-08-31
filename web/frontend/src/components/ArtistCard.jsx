import React, { useState, useEffect } from "react";
import "./ArtistCard.css";

function ArtistCard({ artistId, isOpen, onClose, onFromHere, onToHere }) {
  const [artistData, setArtistData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showFullBio, setShowFullBio] = useState(false);

  useEffect(() => {
    if (artistId && isOpen) {
      fetchArtistData();
    }
  }, [artistId, isOpen]);

  const fetchArtistData = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/artist/${artistId}`);
      if (!response.ok) {
        throw new Error('Artist not found');
      }
      const data = await response.json();
      setArtistData(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleFromHere = () => {
    onFromHere(artistData);
  };

  const handleToHere = () => {
    onToHere(artistData);
  };

  const renderBio = () => {
    if (!artistData?.lastfm_data?.bio_summary) return null;

    const bioText = showFullBio 
      ? artistData.lastfm_data.bio_full || artistData.lastfm_data.bio_summary
      : artistData.lastfm_data.bio_summary;

    // Convert newlines to <br> tags for proper rendering
    const bioWithBreaks = bioText.replace(/\n/g, '<br>');

    return (
      <div className="artist-bio">
        <div 
          className="bio-text"
          dangerouslySetInnerHTML={{ __html: bioWithBreaks }}
        />
        {artistData.lastfm_data.bio_full && artistData.lastfm_data.bio_full !== artistData.lastfm_data.bio_summary && (
          <button 
            className="bio-toggle"
            onClick={() => setShowFullBio(!showFullBio)}
          >
            {showFullBio ? "Show less" : "Read more"}
          </button>
        )}
      </div>
    );
  };

  const formatNumber = (numStr) => {
    if (!numStr) return "—";
    return parseInt(numStr).toLocaleString();
  };

  if (!isOpen) return null;

  return (
    <div className={`artist-card ${isOpen ? 'open' : ''}`}>
      <div className="artist-card-header">
        <button className="close-button" onClick={onClose}>×</button>
      </div>

      {loading && (
        <div className="artist-card-loading">
          <p>Loading artist details...</p>
        </div>
      )}

      {error && (
        <div className="artist-card-error">
          <p>Error: {error}</p>
          {artistData && (
            <div className="fallback-info">
              <h3>{artistData.name}</h3>
              <a href={artistData.url} target="_blank" rel="noopener noreferrer">
                View on Last.fm
              </a>
            </div>
          )}
        </div>
      )}

      {artistData && !loading && !error && (
        <div className="artist-card-content">
          {/* Artist Header */}
          <div className="artist-header">
            {artistData.lastfm_data?.image_url && (
              <img 
                src={artistData.lastfm_data.image_url} 
                alt={artistData.name}
                className="artist-image"
              />
            )}
            <div className="artist-info">
              <h3>{artistData.name}</h3>
              <a 
                href={artistData.lastfm_data?.url || artistData.url} 
                target="_blank" 
                rel="noopener noreferrer"
                className="artist-link"
              >
                View on Last.fm →
              </a>
            </div>
          </div>

          {/* Stats */}
          {artistData.lastfm_data && (
            <div className="artist-stats">
              <div className="stat">
                <span className="stat-label">Listeners</span>
                <span className="stat-value">{formatNumber(artistData.lastfm_data.listeners)}</span>
              </div>
              <div className="stat">
                <span className="stat-label">Plays</span>
                <span className="stat-value">{formatNumber(artistData.lastfm_data.plays)}</span>
              </div>
            </div>
          )}

          {/* Tags */}
          {artistData.lastfm_data?.tags?.length > 0 && (
            <div className="artist-tags">
              <span className="tags-label">Tags:</span>
              <div className="tags">
                {artistData.lastfm_data.tags.slice(0, 5).map((tag, index) => (
                  <span key={index} className="tag">{tag}</span>
                ))}
              </div>
            </div>
          )}

          {/* Bio */}
          {renderBio()}

          {/* Top Tracks */}
          {artistData.top_tracks?.length > 0 && (
            <div className="top-tracks">
              <h4>Top Tracks</h4>
              <div className="tracks-list">
                {artistData.top_tracks.map((track, index) => (
                  <div key={index} className="track">
                    <a 
                      href={track.url} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="track-link"
                    >
                      <span className="track-name">{track.name}</span>
                      <span className="track-stats">
                        {formatNumber(track.playcount)} plays
                      </span>
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>
      )}
      
      {/* Action buttons outside of scrollable content */}
      {artistData && !loading && !error && (
        <div className="artist-actions">
          <button className="action-button from-button" onClick={handleFromHere}>
            from here
          </button>
          <button className="action-button to-button" onClick={handleToHere}>
            to here
          </button>
        </div>
      )}
    </div>
  );
}

export default ArtistCard;