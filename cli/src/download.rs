use indicatif::{ProgressBar, ProgressStyle};
use std::{
    fs,
    io::{Read, Write},
    path::PathBuf,
};

const RELEASE_URL: &str = "https://github.com/malbiruk/artistpath/releases/download/data-v1.1.0/artistpath-data-850k-binary-v1.1.0.tar.zst";

pub fn ensure_data_downloaded() -> Result<PathBuf, Box<dyn std::error::Error>> {
    let home_dir = dirs::home_dir().ok_or("Could not find home directory")?;
    let data_dir = home_dir.join(".artistpath");

    // Check if data already exists (including new reverse graph)
    let metadata_path = data_dir.join("metadata.bin");
    let graph_path = data_dir.join("graph.bin");
    let reverse_graph_path = data_dir.join("rev-graph.bin");

    if metadata_path.exists() && graph_path.exists() && reverse_graph_path.exists() {
        return Ok(data_dir);
    }

    println!("📦 Data not found, downloading dataset...");

    // Create directory if it doesn't exist
    fs::create_dir_all(&data_dir)?;

    // Download the archive
    let archive_path = data_dir.join("artistpath-data.tar.zst");
    download_with_progress(RELEASE_URL, &archive_path)?;

    // Extract the archive
    println!("🗜️  Extracting data...");
    extract_zstd_tar(&archive_path, &data_dir)?;

    // Clean up archive
    fs::remove_file(&archive_path)?;

    println!("✅ Dataset ready!");

    Ok(data_dir)
}

fn download_with_progress(url: &str, dest: &PathBuf) -> Result<(), Box<dyn std::error::Error>> {
    let mut response = reqwest::blocking::get(url)?;
    let total_size = response.content_length().unwrap_or(0);

    let pb = ProgressBar::new(total_size);
    pb.set_style(
        ProgressStyle::with_template("{spinner:.green} [{elapsed_precise}] [{wide_bar:.cyan/blue}] {bytes}/{total_bytes} ({bytes_per_sec}, {eta})")?
            .progress_chars("#>-")
    );

    let mut file = fs::File::create(dest)?;
    let mut downloaded: u64 = 0;
    let mut buffer = [0; 8192];

    loop {
        let bytes_read = response.read(&mut buffer)?;
        if bytes_read == 0 {
            break;
        }
        file.write_all(&buffer[..bytes_read])?;
        downloaded += bytes_read as u64;
        pb.set_position(downloaded);
    }

    pb.finish_with_message("Download complete");
    Ok(())
}

fn extract_zstd_tar(
    archive_path: &PathBuf,
    dest_dir: &PathBuf,
) -> Result<(), Box<dyn std::error::Error>> {
    use std::process::Command;

    let output = Command::new("tar")
        .args(["--use-compress-program=zstd", "-xf"])
        .arg(archive_path)
        .arg("-C")
        .arg(dest_dir)
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Failed to extract archive: {}", stderr).into());
    }

    Ok(())
}
