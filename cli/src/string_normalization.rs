use pyo3::prelude::*;
use slugify::slugify;

#[pyfunction]
fn clean_str(input: &str) -> String {
    input
        .trim()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<&str>>()
        .join(" ")
}

fn remove_punctuation(input: &str) -> String {
    clean_str(input)
        .chars()
        .filter(|c| !c.is_ascii_punctuation())
        .collect()
}

fn remove_articles(input: &str) -> String {
    clean_str(input)
        .split_whitespace()
        .filter(|word| !["a", "an", "the"].contains(word))
        .collect::<Vec<&str>>()
        .join(" ")
}

#[pyfunction]
fn normalize_str(input: &str) -> String {
    remove_punctuation(&remove_articles(&clean_str(input)))
}

#[pyfunction]
fn to_slug(input: &str) -> String {
    slugify!(&normalize_str(input))
}

#[pymodule]
fn normalization(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(clean_str, m)?)?;
    m.add_function(wrap_pyfunction!(normalize_str, m)?)?;
    m.add_function(wrap_pyfunction!(to_slug, m)?)?;
    Ok(())
}
