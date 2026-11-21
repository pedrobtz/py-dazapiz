# Generate tests/fixtures/azr_spark_conf.json from azr::azure_spark_storage_conf().
#
# Usage, from the repository root:
#
#   Rscript tools/azr_spark_fixture.R <path to an azr checkout> [output file]
#
# Loads the checkout with pkgload::load_all() (azr need not be installed) and
# runs every auth_type x storage_account (none, short, FQDN) x authority_host
# (public, US Gov, China) x prefix (default, NULL), with every argument passed
# explicitly and placeholder secrets, so no default and no environment
# variable is involved. A few variants follow: an authority host given as a
# URL with a trailing slash, and a prefix with a trailing dot, which azr
# normalises. A combination azr refuses is recorded as an expected error
# rather than dropped. Design §8.1; rerun when azr changes.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1L) {
  stop("usage: Rscript tools/azr_spark_fixture.R <azr checkout> [output file]")
}
azr_path <- normalizePath(args[[1]], mustWork = TRUE)
out_file <- if (length(args) >= 2L) args[[2]] else "tests/fixtures/azr_spark_conf.json"

options(cli.num_colors = 1L)
Sys.unsetenv(c(
  "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET",
  "AZURE_REFRESH_TOKEN", "AZURE_FEDERATED_TOKEN_FILE", "AZURE_AUTHORITY_HOST"
))

suppressMessages(pkgload::load_all(azr_path, quiet = TRUE, export_all = FALSE))
azr_conf <- get("azure_spark_storage_conf", envir = asNamespace("azr"))

git <- function(...) {
  system2("git", c("-C", shQuote(azr_path), ...), stdout = TRUE)
}
azr_commit <- git("rev-parse", "HEAD")
azr_dirty <- length(git("status", "--porcelain", "--untracked-files=no")) > 0L
azr_version <- unname(read.dcf(file.path(azr_path, "DESCRIPTION"), "Version")[1, 1])

auth_types <- c(
  "refresh_token", "client_secret", "workload_identity",
  "managed_identity", "shared_key"
)
storage_accounts <- list(
  none = NULL,
  short = "placeholderacct",
  fqdn = "placeholderacct.dfs.core.windows.net"
)
authority_hosts <- c(
  public = "login.microsoftonline.com",
  us_gov = "login.microsoftonline.us",
  china = "login.chinacloudapi.cn"
)
prefixes <- list(default = "spark.hadoop", null = NULL)

# Placeholder values, never real credentials.
fixed_args <- list(
  tenant_id = "00000000-0000-0000-0000-00000000aaaa",
  client_id = "00000000-0000-0000-0000-00000000bbbb",
  client_secret = "placeholder-client-secret",
  refresh_token = "placeholder-refresh-token",
  account_key = "placeholder-account-key",
  token_file = "/var/run/secrets/azure/tokens/azure-identity-token"
)

# Build the argument list; `x[name] <- list(NULL)` keeps a NULL element.
make_args <- function(auth_type, storage_account, authority_host, prefix) {
  a <- c(list(auth_type = auth_type), list(storage_account = NULL), fixed_args)
  a["storage_account"] <- list(storage_account)
  a$authority_host <- authority_host
  a["prefix"] <- list(prefix)
  a
}

run_case <- function(id, a) {
  result <- tryCatch(
    list(conf = unclass(do.call(azr_conf, a))),
    error = function(e) list(error = cli::ansi_strip(conditionMessage(e)))
  )
  c(list(id = id, args = a), result)
}

cases <- list()
for (auth_type in auth_types) {
  for (sa in names(storage_accounts)) {
    for (host in names(authority_hosts)) {
      for (pf in names(prefixes)) {
        id <- paste(auth_type, sa, host, pf, sep = "/")
        a <- make_args(
          auth_type, storage_accounts[[sa]], authority_hosts[[host]], prefixes[[pf]]
        )
        cases[[length(cases) + 1L]] <- run_case(id, a)
      }
    }
  }
}

# Variants: inputs azr normalises.
for (auth_type in auth_types) {
  id <- paste(auth_type, "short", "us_gov_url", "default", sep = "/")
  a <- make_args(auth_type, "placeholderacct", "https://login.microsoftonline.us/", "spark.hadoop")
  cases[[length(cases) + 1L]] <- run_case(id, a)

  id <- paste(auth_type, "short", "public", "trailing_dot", sep = "/")
  a <- make_args(auth_type, "placeholderacct", "login.microsoftonline.com", "spark.hadoop.")
  cases[[length(cases) + 1L]] <- run_case(id, a)
}

fixture <- list(
  generator = "tools/azr_spark_fixture.R",
  azr_commit = azr_commit,
  azr_dirty = azr_dirty,
  azr_version = azr_version,
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  cases = cases
)

dir.create(dirname(out_file), showWarnings = FALSE, recursive = TRUE)
json <- jsonlite::toJSON(fixture, auto_unbox = TRUE, null = "null", pretty = TRUE, digits = NA)
writeLines(json, out_file, useBytes = TRUE)
n_err <- sum(vapply(cases, function(x) !is.null(x$error), logical(1)))
message(sprintf(
  "Wrote %d cases (%d expected errors) from azr %s (%s) to %s",
  length(cases), n_err, azr_version, substr(azr_commit, 1, 7), out_file
))
