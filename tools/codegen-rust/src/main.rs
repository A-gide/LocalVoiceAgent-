//! Generates the Rust IPC contract from a normalized JSON Schema.
//!
//! Reads the schema path from `argv[1]` and writes the generated Rust to
//! stdout.  Any failure is reported on stderr with a non-zero exit status so
//! the calling codegen step can abort instead of writing a partial artifact.

use std::process::ExitCode;

const EXIT_USAGE: u8 = 2;
const EXIT_READ: u8 = 3;
const EXIT_JSON: u8 = 4;
const EXIT_SCHEMA: u8 = 5;
const EXIT_TYPIFY: u8 = 6;
const EXIT_SYN: u8 = 7;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: lva-codegen-rust <normalized-schema.json | ->");
        return ExitCode::from(EXIT_USAGE);
    }

    let text = if args[1] == "-" {
        use std::io::Read;
        let mut buffer = String::new();
        if let Err(err) = std::io::stdin().read_to_string(&mut buffer) {
            eprintln!("cannot read stdin: {err}");
            return ExitCode::from(EXIT_READ);
        }
        buffer
    } else {
        match std::fs::read_to_string(&args[1]) {
            Ok(text) => text,
            Err(err) => {
                eprintln!("cannot read {}: {err}", args[1]);
                return ExitCode::from(EXIT_READ);
            }
        }
    };

    let value: serde_json::Value = match serde_json::from_str(&text) {
        Ok(value) => value,
        Err(err) => {
            eprintln!("invalid JSON: {err}");
            return ExitCode::from(EXIT_JSON);
        }
    };

    let schema: schemars::schema::RootSchema = match serde_json::from_value(value) {
        Ok(schema) => schema,
        Err(err) => {
            eprintln!("schema is not a JSON Schema document: {err}");
            return ExitCode::from(EXIT_SCHEMA);
        }
    };

    // typify already derives serde::{Serialize, Deserialize}; only add the
    // traits it does not emit, otherwise the derives are duplicated.
    let mut settings = typify::TypeSpaceSettings::default();
    settings.with_derive("Debug".to_string());
    settings.with_derive("Clone".to_string());

    let mut space = typify::TypeSpace::new(&settings);
    if let Err(err) = space.add_root_schema(schema) {
        eprintln!("typify rejected the schema: {err}");
        return ExitCode::from(EXIT_TYPIFY);
    }

    let file = match syn::parse2::<syn::File>(space.to_stream()) {
        Ok(file) => file,
        Err(err) => {
            eprintln!("generated tokens do not parse: {err}");
            return ExitCode::from(EXIT_SYN);
        }
    };

    println!("{}", prettyplease::unparse(&file));
    ExitCode::SUCCESS
}