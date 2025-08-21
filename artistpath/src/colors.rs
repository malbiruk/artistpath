use colored::*;

pub struct ColorScheme;

impl ColorScheme {
    pub fn new(use_colors: bool) -> Self {
        if !use_colors {
            colored::control::set_override(false);
        }
        Self
    }

    pub fn artist_name(&self, text: &str) -> ColoredString {
        text.yellow()
    }

    pub fn url(&self, text: &str) -> ColoredString {
        text.normal()
    }

    pub fn success(&self, text: &str) -> ColoredString {
        text.green()
    }

    pub fn error(&self, text: &str) -> ColoredString {
        text.red()
    }

    pub fn step_number(&self, text: &str) -> ColoredString {
        text.blue()
    }

    pub fn similarity(&self, text: &str) -> ColoredString {
        text.normal()
    }

    pub fn number(&self, text: &str) -> ColoredString {
        text.green()
    }

    pub fn stats(&self, text: &str) -> ColoredString {
        text.blue()
    }
}
