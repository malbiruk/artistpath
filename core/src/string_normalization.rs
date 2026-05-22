use unidecode::unidecode;

pub fn clean_str(input: &str) -> String {
    unidecode(input)
        .trim()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<&str>>()
        .join(" ")
}
