use unidecode::unidecode;

pub fn clean_str(input: &str) -> String {
    unidecode(input)
        .trim()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<&str>>()
        .join(" ")
}

/// Articles to strip from the front of a normalized name when looking for
/// "canonical" matches. Order matters: longer prefixes first to avoid
/// stripping "the" out of "the the".
const LEADING_ARTICLES: &[&str] = &[
    "the ", "los ", "las ", "les ", "der ", "die ", "das ", "gli ",
    "an ", "el ", "la ", "le ", "il ", "lo ", "a ",
];

/// Strip a single leading article from a `clean_str`-normalized string.
/// Returns the original slice if no article is present, or if stripping
/// would leave the string empty (so "the" still matches "the").
pub fn strip_leading_article(s: &str) -> &str {
    for article in LEADING_ARTICLES {
        if let Some(rest) = s.strip_prefix(article) {
            if !rest.is_empty() {
                return rest;
            }
        }
    }
    s
}

/// Iterator over byte trigrams of a string. After `clean_str` the input
/// is ASCII (unidecode transliterates), so byte trigrams == char trigrams
/// and align with substring matching, which is also byte-level.
pub fn extract_trigrams(s: &str) -> impl Iterator<Item = [u8; 3]> + '_ {
    let bytes = s.as_bytes();
    (0..bytes.len().saturating_sub(2)).map(move |i| [bytes[i], bytes[i + 1], bytes[i + 2]])
}

/// Markers that strongly indicate a collaboration entry rather than a
/// canonical artist. Leading/trailing spaces avoid matching inside words
/// (e.g. "feathers", "drift"). Extend with " x ", " vs ", " with " etc.
/// only if false-positive risk is acceptable for your data.
const COLLAB_MARKERS: &[&str] = &[
    " feat. ",
    " feat ",
    " ft. ",
    " ft ",
    " featuring ",
];

/// Returns true if `normalized_name` (already lowercased via `clean_str`)
/// looks like a feat/ft/featuring collaboration entry. Used to demote these
/// in search ranking; entries remain in the dataset and graph.
pub fn is_collab_entry(normalized_name: &str) -> bool {
    COLLAB_MARKERS.iter().any(|m| normalized_name.contains(m))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_known_articles() {
        assert_eq!(strip_leading_article("the beatles"), "beatles");
        assert_eq!(strip_leading_article("los lobos"), "lobos");
        assert_eq!(strip_leading_article("die toten hosen"), "toten hosen");
    }

    #[test]
    fn keeps_string_when_no_article() {
        assert_eq!(strip_leading_article("beatles"), "beatles");
        assert_eq!(strip_leading_article("queen"), "queen");
    }

    #[test]
    fn does_not_empty_string_when_only_article() {
        // "the the" should NOT become empty — keep at least one token.
        assert_eq!(strip_leading_article("the"), "the");
        // But "the the" strips the first "the " leaving "the".
        assert_eq!(strip_leading_article("the the"), "the");
    }

    #[test]
    fn extracts_byte_trigrams() {
        let tg: Vec<[u8; 3]> = extract_trigrams("beatles").collect();
        assert_eq!(tg.len(), 5);
        assert_eq!(tg[0], *b"bea");
        assert_eq!(tg[4], *b"les");
    }

    #[test]
    fn short_strings_yield_no_trigrams() {
        assert_eq!(extract_trigrams("").count(), 0);
        assert_eq!(extract_trigrams("ab").count(), 0);
        assert_eq!(extract_trigrams("abc").count(), 1);
    }

    #[test]
    fn detects_collab_entries() {
        assert!(is_collab_entry("drake feat. future"));
        assert!(is_collab_entry("drake feat future"));
        assert!(is_collab_entry("drake ft. future"));
        assert!(is_collab_entry("drake ft future"));
        assert!(is_collab_entry("drake featuring future"));
    }

    #[test]
    fn keeps_canonical_artists() {
        assert!(!is_collab_entry("drake"));
        assert!(!is_collab_entry("the beatles"));
        // " feat" at end or start with no trailing space is not a marker
        assert!(!is_collab_entry("feathers"));
        assert!(!is_collab_entry("ft island"));
    }
}
