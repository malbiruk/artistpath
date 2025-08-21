use pyo3::prelude::*;
use unidecode::unidecode;

#[pyfunction]
pub fn clean_str(input: &str) -> String {
    unidecode(input) // Convert Unicode to ASCII
        .trim()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<&str>>()
        .join(" ")
}

#[pymodule]
fn normalization(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(clean_str, m)?)?;
    Ok(())
}
