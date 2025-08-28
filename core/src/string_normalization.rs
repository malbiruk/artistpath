use unidecode::unidecode;

#[cfg(feature = "python")]
use pyo3::prelude::*;

#[cfg_attr(feature = "python", pyfunction)]
pub fn clean_str(input: &str) -> String {
    unidecode(input) // Convert Unicode to ASCII
        .trim()
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<&str>>()
        .join(" ")
}

#[cfg(feature = "python")]
#[pymodule]
pub fn normalization(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(clean_str, m)?)?;
    Ok(())
}
