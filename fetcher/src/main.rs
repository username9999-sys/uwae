use clap::Parser;
use serde_json::json;

#[derive(Parser)]
#[command(
    name = "uwae-fetch",
    version,
    about = "Fetch any URL to clean markdown for AI agents"
)]
struct Args {
    /// URL to fetch
    url: String,
    /// Emit JSON instead of raw markdown
    #[arg(long)]
    json: bool,
    /// Timeout in seconds
    #[arg(long, default_value_t = 15)]
    timeout: u64,
    /// Max response bytes to read
    #[arg(long, default_value_t = 5_000_000)]
    max_bytes: usize,
}

/// Remove <script>/<style>/<noscript> blocks so their source never leaks
/// into the markdown output.
fn strip_non_content(html: &str) -> String {
    let mut out = String::with_capacity(html.len());
    let mut rest = html;
    loop {
        let lower = rest.to_lowercase();
        let start = ["<script", "<style", "<noscript"]
            .iter()
            .filter_map(|t| lower.find(t))
            .min();
        let Some(start) = start else {
            out.push_str(rest);
            return out;
        };
        out.push_str(&rest[..start]);
        let after_open = &rest[start..];
        let gt = after_open.find('>').map(|i| start + i + 1);
        let Some(gt) = gt else {
            return out;
        };
        let tag = lower[start..].chars().take(9).collect::<String>();
        let close = if tag.starts_with("<script") {
            "</script>"
        } else if tag.starts_with("<style") {
            "</style>"
        } else {
            "</noscript>"
        };
        let end = lower[gt..]
            .find(close)
            .map(|i| gt + i + close.len())
            .unwrap_or(rest.len());
        rest = &rest[end..];
    }
}

fn extract_title(html: &str) -> String {
    let lower = html.to_lowercase();
    if let Some(start) = lower.find("<title") {
        if let Some(gt) = lower[start..].find('>') {
            let rest = &html[start + gt + 1..];
            if let Some(end) = rest.to_lowercase().find("</title>") {
                return rest[..end].trim().to_string();
            }
        }
    }
    String::new()
}

fn main() {
    let args = Args::parse();
    let client = match reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(args.timeout))
        .user_agent("uwae-fetch/0.1 (+https://github.com/username9999-sys/uwae)")
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            eprintln!("client build failed: {e}");
            std::process::exit(2);
        }
    };
    let resp = match client.get(&args.url).send() {
        Ok(r) => r,
        Err(e) => {
            eprintln!("fetch failed: {e}");
            std::process::exit(1);
        }
    };
    let status = resp.status().as_u16();
    let final_url = resp.url().to_string();
    let content_type = resp
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let bytes = match resp.bytes() {
        Ok(b) => b,
        Err(e) => {
            eprintln!("read failed: {e}");
            std::process::exit(1);
        }
    };
    let total_bytes = bytes.len();
    let truncated = total_bytes > args.max_bytes;
    let body = &bytes[..total_bytes.min(args.max_bytes)];
    let raw = String::from_utf8_lossy(body).to_string();
    let is_html = content_type.contains("html");
    let text = if is_html { strip_non_content(&raw) } else { raw };
    let title = extract_title(&text);
    let markdown = if is_html {
        html2md::parse_html(&text)
    } else {
        text
    };
    if args.json {
        println!(
            "{}",
            json!({
                "url": args.url,
                "final_url": final_url,
                "status": status,
                "content_type": content_type,
                "bytes": bytes.len(),
                "truncated": truncated,
                "title": title,
                "markdown": markdown,
            })
        );
    } else if !title.is_empty() {
        println!("# {title}\n");
        print!("{markdown}");
    } else {
        print!("{markdown}");
    }
}
