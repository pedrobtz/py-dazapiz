# Generate tests/fixtures/azr_json_body.json from azr's format_json_body().
#
# Usage, from the repository root:
#
#   Rscript tools/azr_json_body_fixture.R <path to an azr checkout> [output file]
#
# Loads the checkout with pkgload::load_all() (azr need not be installed) and
# runs the internal format_json_body() on JSON text, as azr's .send_request()
# does with a request body (default max_size = 12, max_items = 10; the body
# params httr2's req_body_raw() leaves are NULL, so auto_unbox = TRUE and
# null = "null"). Each case records the input JSON text and azr's output.
# Some cases show jsonlite quirks the Python port does not copy; the test
# says which, and design §4.1 lists them. Rerun when azr changes.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1L) {
  stop("usage: Rscript tools/azr_json_body_fixture.R <azr checkout> [output file]")
}
azr_path <- normalizePath(args[[1]], mustWork = TRUE)
out_file <- if (length(args) >= 2L) args[[2]] else "tests/fixtures/azr_json_body.json"

# jsonlite writes non-ASCII as-is only in a UTF-8 locale.
invisible(Sys.setlocale("LC_CTYPE", "en_US.UTF-8"))
if (!l10n_info()[["UTF-8"]]) stop("a UTF-8 locale is needed")

suppressMessages(pkgload::load_all(azr_path, quiet = TRUE, export_all = FALSE))
format_json_body <- get("format_json_body", envir = asNamespace("azr"))

git <- function(...) {
  system2("git", c("-C", shQuote(azr_path), ...), stdout = TRUE)
}
azr_commit <- git("rev-parse", "HEAD")
azr_dirty <- length(git("status", "--porcelain", "--untracked-files=no")) > 0L
azr_version <- unname(read.dcf(file.path(azr_path, "DESCRIPTION"), "Version")[1, 1])

# JSON text helpers, so each input is written exactly as sent.
arr <- function(x) paste0("[", paste(x, collapse = ","), "]")
obj <- function(keys, values) {
  paste0("{", paste0('"', keys, '":', values, collapse = ","), "}")
}
str <- function(x) paste0('"', x, '"')
small <- function(i) obj(c("id", "ok"), c(i, if (i %% 2L) "true" else "false"))
keys <- function(n) sprintf("k%02d", seq_len(n))

resource <- function(i) {
  name <- sprintf("rg-%02d", i)
  obj(
    c("id", "name", "type", "location", "tags", "properties"),
    c(
      str(paste0("/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/", name)),
      str(name),
      str("Microsoft.Resources/resourceGroups"),
      str(if (i %% 2L) "westeurope" else "northeurope"),
      if (i %% 3L) "{}" else obj("env", str("dev")),
      obj("provisioningState", str("Succeeded"))
    )
  )
}

inputs <- list(
  # Objects: max_items = 10 applies; names kept around "...".
  object_10 = obj(keys(10), seq_len(10)),
  object_11 = obj(keys(11), seq_len(11)),
  object_15_mixed = obj(
    keys(15),
    c(str(letters[1:5]), "null", "true", "false", "[]", "{}", "0.5", "-7", str("x"), "1", "2")
  ),
  # A top-level array of scalars is a list to inner_format(): max_items.
  array_10 = arr(seq_len(10)),
  array_11 = arr(seq_len(11)),
  array_13 = arr(seq_len(13)),
  # Arrays of objects: max_items.
  array_of_objects_10 = obj("value", arr(vapply(1:10, small, ""))),
  array_of_objects_11 = obj("value", arr(vapply(1:11, small, ""))),
  # Nested arrays of scalars are atomic vectors: max_size = 12.
  atomic_strings_11 = obj("x", arr(str(letters[1:11]))),
  atomic_strings_12 = obj("x", arr(str(letters[1:12]))),
  atomic_strings_13 = obj("x", arr(str(letters[1:13]))),
  atomic_numbers_12 = obj("x", arr(seq_len(12))),
  atomic_numbers_13 = obj("x", arr(seq_len(13))),
  atomic_booleans_13 = obj("x", arr(rep(c("true", "false"), length.out = 13))),
  # Lists of lists, truncated at more than one level.
  nested_arrays = obj("a", arr(c(arr(1:2), arr(3:4), arr(str(letters[1:13]))))),
  nested_deep = obj(
    "outer",
    arr(vapply(1:11, function(i) obj(c("i", "inner"), c(i, arr(str(letters[1:13])))), ""))
  ),
  nested_objects = obj("a", obj(keys(11), vapply(1:11, function(i) obj("b", arr(1:3)), ""))),
  # Empty containers and scalars.
  empty_array = "[]",
  empty_object = "{}",
  empty_members = obj(c("a", "b"), c("[]", "{}")),
  scalars = obj(
    c("n", "t", "f", "i", "neg", "half", "s", "u"),
    c("null", "true", "false", "42", "-7", "0.5", str("plain"), str("é ✓ 日本 \U0001f600"))
  ),
  atomic_booleans_with_null = obj("a", arr(c("true", "false", "null"))),
  escapes = obj("a", str('line\\nbreak \\"q\\" \\\\ / \\t tab')),
  # jsonlite quirks, listed in design §4.1.
  atomic_numbers_with_null = obj("a", arr(c("1", "null", "3"))),
  atomic_mixed = obj("a", arr(c("1", str("x"), "true"))),
  # An ARM list response.
  arm_list = obj(c("value", "nextLink"), c(arr(vapply(1:30, resource, "")), "null"))
)

cases <- lapply(names(inputs), function(id) {
  input <- inputs[[id]]
  stopifnot(jsonlite::validate(input))
  list(id = id, input = input, azr = as.character(format_json_body(input)))
})

fixture <- list(
  generator = "tools/azr_json_body_fixture.R",
  azr_commit = azr_commit,
  azr_dirty = azr_dirty,
  azr_version = azr_version,
  jsonlite_version = as.character(utils::packageVersion("jsonlite")),
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  cases = cases
)

dir.create(dirname(out_file), showWarnings = FALSE, recursive = TRUE)
json <- jsonlite::toJSON(fixture, auto_unbox = TRUE, null = "null", pretty = TRUE)
writeLines(enc2utf8(json), out_file, useBytes = TRUE)
message(sprintf(
  "Wrote %d cases from azr %s (%s) to %s",
  length(cases), azr_version, substr(azr_commit, 1, 7), out_file
))
