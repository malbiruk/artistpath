use artistpath::string_normalization::clean_str;

#[test]
fn test_clean_str_basic() {
    assert_eq!(clean_str("hello world"), "hello world");
    assert_eq!(clean_str("HELLO WORLD"), "hello world");
    assert_eq!(clean_str("  hello  world  "), "hello world");
}

#[test]
fn test_clean_str_unicode() {
    assert_eq!(clean_str("Björk"), "bjork");
    assert_eq!(clean_str("Beyoncé"), "beyonce");
    assert_eq!(clean_str("LØLØ"), "lolo");
    assert_eq!(clean_str("Röyksopp"), "royksopp");
}

#[test]
fn test_clean_str_special_characters() {
    assert_eq!(clean_str("AC/DC"), "ac/dc");
    assert_eq!(clean_str("Panic! At The Disco"), "panic! at the disco");
    assert_eq!(clean_str("blink-182"), "blink-182");
}

#[test]
fn test_clean_str_extra_spaces() {
    assert_eq!(clean_str("   Taylor   Swift   "), "taylor swift");
    assert_eq!(clean_str("The\t\tBeatles"), "the beatles");
    assert_eq!(clean_str("Pink\nFloyd"), "pink floyd");
}

#[test]
fn test_clean_str_empty() {
    assert_eq!(clean_str(""), "");
    assert_eq!(clean_str("   "), "");
    assert_eq!(clean_str("\t\n"), "");
}