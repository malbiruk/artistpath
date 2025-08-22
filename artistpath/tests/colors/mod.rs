use artistpath::colors::ColorScheme;

#[test]
fn test_color_scheme_with_colors() {
    let colors = ColorScheme::new(true);
    
    // Just verify methods don't panic and return ColoredString
    let artist = colors.artist_name("Test Artist");
    assert!(artist.to_string().contains("Test Artist"));
    
    let url = colors.url("https://example.com");
    assert!(url.to_string().contains("https://example.com"));
    
    let success = colors.success("Success");
    assert!(success.to_string().contains("Success"));
    
    let error = colors.error("Error");
    assert!(error.to_string().contains("Error"));
    
    let step = colors.step_number("1.");
    assert!(step.to_string().contains("1."));
    
    let sim = colors.similarity("[0.5]");
    assert!(sim.to_string().contains("[0.5]"));
    
    let num = colors.number("123");
    assert!(num.to_string().contains("123"));
    
    let stats = colors.stats("Stats");
    assert!(stats.to_string().contains("Stats"));
}

#[test]
fn test_color_scheme_no_colors() {
    let colors = ColorScheme::new(false);
    
    // With colors disabled, output should be plain text
    let artist = colors.artist_name("Test Artist");
    assert_eq!(artist.to_string(), "Test Artist");
    
    let url = colors.url("https://example.com");
    assert_eq!(url.to_string(), "https://example.com");
    
    let success = colors.success("Success");
    assert_eq!(success.to_string(), "Success");
    
    let error = colors.error("Error");
    assert_eq!(error.to_string(), "Error");
}