# Every container was "healthy". My traces went nowhere.

I went into the [Agents of SigNoz hackathon](https://www.wemakedevs.org/hackathons/signoz)
thinking that self-hosting SigNoz would essentially be a boring docker-compose
afternoon. Instead I ended up learning that SigNoz's ingest ports do not open
until you create a user account, that the install path every tutorial on the
internet describes does not exist anymore, and that a histogram will very
confidently tell you every coffee takes 4.95 seconds to brew if you let it.
This is a write-up of what actually happened, on one MacBook, in one evening.

## What I was trying to do

The hackathon asks you to self-host SigNoz, send real telemetry to it, and
explore the features properly. Now I could have instrumented a hello-world and
called it a day, but I feel you never really learn anything from an app that
cannot fail. So I built **brewlog**: a small coffee-shop API in FastAPI, split
into two services. `brewlog-api` takes your order and calls `brew-machine`
over HTTP, which "brews" the drink. I added some deliberate chaos to it: 8% of
brews fail with a random "machine jammed" error, and pour_over is
intentionally ~10x slower than espresso, so that there is a genuine p99
outlier hiding in there for me to hunt later. SQLite underneath, httpx between
the services. Boring on purpose, chaotic on purpose.

## Setup: the tutorials have not caught up

I do not run Docker Desktop, so my first stop was Colima:

```bash
brew install colima docker docker-compose
colima start --cpu 4 --memory 8 --disk 60
```

One small gotcha here: Homebrew's compose is a CLI plugin, and `docker
compose` will simply not find it until you add this to
`~/.docker/config.json`:

```json
{ "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"] }
```

Then I cloned SigNoz and went looking for `deploy/docker/docker-compose.yaml`,
because that is what every blog post from the last three years tells you to
do. It is gone. The `deploy/` directory now just contains a README politely
informing you that the compose manifests are deprecated, and that SigNoz now
installs through **Foundry**, a new CLI which has fully committed to the
metallurgy theme: you install `foundryctl`, you write a `casting.yaml`, you
run `foundryctl cast`, and the generated compose files land in a directory
called `pours/`.

```yaml
apiVersion: v1alpha1
kind: Installation
metadata:
  name: signoz
spec:
  deployment:
    flavor: compose
    mode: docker
  mcp:
    spec:
      enabled: true
```

That `mcp` block also gives you SigNoz's MCP server on port 8000, so AI
agents can query your telemetry, which I have plans for during the main
hackathon week. One `cast` later I had seven containers running: the SigNoz
server, an OpenTelemetry collector, ClickHouse, clickhouse-keeper, a Postgres
metastore, a migrator, and the MCP server. Every single one reported healthy.
The UI loaded on localhost:8080. Great, I thought.

## The trap: ingestion is gated on signup, and nobody tells you

I wired the app up with OpenTelemetry auto-instrumentation and pointed it at
`localhost:4317`. The exports immediately started dying:

```
Transient error StatusCode.UNAVAILABLE encountered while exporting traces
to localhost:4317 ... Socket closed
```

Socket *closed*, not refused. So Docker was accepting my connection, and then
the collector was hanging up on me. I sat with this for a while. Was the port
mapping wrong? Was Colima doing something strange? Was the collector still
booting? The collector container ships with no ps and no netstat, so I ended
up reading `/proc/net/tcp` directly and converting the hex ports by hand
(4317 is 0x10DD, in case this ever saves you an evening). Only the
collector's pprof, internal metrics and healthcheck ports were listening. No
4317, no 4318. And yet the generated `ingester.yaml` very clearly configures
OTLP receivers on both.

The answer was sitting in the SigNoz server logs, repeating every 30 seconds:

```
failed to find or create agent ... cannot create agent without orgId
```

It turns out the collector does not read its config file at startup at all.
It connects to the SigNoz server over **OpAMP** and receives its effective
config remotely, and the server refuses to register the agent until an
organization exists, which only happens when the first admin user signs up.
So the entire ingest pipeline is essentially dead until you fill in a signup
form. I registered a user, and about 30 seconds later the OpAMP retry
succeeded and both ports quietly opened.

I do understand the design, config from the control plane is how you build
managed pipelines. But I feel that "telemetry ports will not listen until
first signup" deserves at least one line in the install guide, because that
ordering appears in no doc I could find.

## Instrumentation: the part that just worked

Credit where it is due, this part was almost free:

```bash
pip install opentelemetry-distro opentelemetry-exporter-otlp
opentelemetry-bootstrap -a install
OTEL_SERVICE_NAME=brewlog-api opentelemetry-instrument uvicorn app:app --port 8001
```

FastAPI, httpx and sqlite3 all get traced with zero code changes, and the
trace context propagates across the HTTP hop between my two services on its
own. I added maybe fifteen lines by hand: two custom spans (`grind_beans`,
`extract`), span attributes for the order id and drink, a counter, a
histogram, and one environment variable which quietly became my favorite line
of configuration in the entire project:

```bash
OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true
```

That single line ships every ordinary `logging` call as an OTel log record,
already stamped with the active trace and span IDs. No structured logging
library, no JSON formatter, nothing.

[![Services list showing brew-machine at an 8.79% error rate](https://raw.githubusercontent.com/ankurgupta255/brewlog/main/shots/hd/services.png)](https://raw.githubusercontent.com/ankurgupta255/brewlog/main/shots/hd/services.png)
*The SigNoz Services page listing both brewlog services. The columns show p99 latency, error rate and operations per second for the selected window; brew-machine sits at an 8.79% error rate because of the injected machine jams.*

## The feature I keep coming back to: one click from a 502 to the log line

Here is the workflow that genuinely sold me. Traffic generator running,
orders flowing, and the Services page shows `brew-machine` sitting at an 8.79%
error rate. I open Traces, filter to errors, and pick a failed `POST /order`.
The flame graph tells the whole story on one screen: ten spans, two services,
the request crossing from `brewlog-api` into `brew-machine`, and at the
bottom a short red `extract` span where the machine jammed. The 500 bubbles
up to the api's outer span as a 502.

[![Flame graph of a failed order, red extract span across two services](https://raw.githubusercontent.com/ankurgupta255/brewlog/main/shots/hd/trace-error-detail.png)](https://raw.githubusercontent.com/ankurgupta255/brewlog/main/shots/hd/trace-error-detail.png)
*Trace detail for one failed order. The flame graph and the waterfall below it show the request travelling from brewlog-api into brew-machine; the short red extract span is the exact point where the machine jammed, and that 500 propagates up to the root span as a 502.*

From that red span, "related logs" lands me directly on the exact
`machine jammed while brewing espresso` line, because the trace and span IDs
were already sitting on the log record thanks to that one environment
variable. The reverse direction works too, from a log line back to its full
trace. I have done this dance across three separate tools before, a metrics
dashboard here, a tracing UI there, a log aggregator in a third tab, each
with its own query language. Having the whole thing inside one tool, with the
join already done for you, is honestly the part I would pay for.

I closed the loop with an alert: a threshold rule on
`(failed orders / total orders) * 100 > 5%`, which the 8% jam rate trips
reliably. For the notification channel I pointed a webhook back at the demo
app itself, which logs the alert, which then ships to SigNoz as a log. So my
observability stack now complains about my coffee machine, to my coffee
machine. There is something oddly satisfying about that.

[![Triggered alert in firing state](https://raw.githubusercontent.com/ankurgupta255/brewlog/main/shots/hd/alerts-triggered.png)](https://raw.githubusercontent.com/ankurgupta255/brewlog/main/shots/hd/alerts-triggered.png)
*The Triggered Alerts tab with the failure-rate rule in Firing state, showing its severity and labels about a minute after the jam rate crossed the 5% threshold.*

## Two more things that bit me

**Histograms do not lie, but buckets absolutely do.** My first p99-by-drink
panel showed every single drink at exactly 4.95s. Espresso takes 50
milliseconds. The cause: OTel's default histogram boundaries start at
[0, 5, 10, ...], so every sub-second brew falls into the (0, 5] bucket, and
quantile interpolation just invents ~4.95s out of thin air. The fix is
`explicit_bucket_boundaries_advisory=[0.025, ..., 3.0]` on the instrument. After the fix
the panel finally separates: pour_over settles at its true ~1.4s while every
other drink stays well under 200ms, where minutes earlier the same panel was
one flat 4.95s line. I feel this one chart taught me more about histograms
than any documentation has.

[![Brewlog Overview dashboard with per-drink p99 after the bucket fix](https://raw.githubusercontent.com/ankurgupta255/brewlog/main/shots/hd/dashboard-brewlog.png)](https://raw.githubusercontent.com/ankurgupta255/brewlog/main/shots/hd/dashboard-brewlog.png)
*The Brewlog Overview dashboard. In the p99 panel, pour_over sits at its true ~1.4s while every other drink stays under 200ms; before the bucket fix this same panel was one flat 4.95s line for all five drinks.*

**And before the buckets could lie to me, the query would not even run.**
ClickHouse said `Function with name 'histogramQuantile' does not exist`.
SigNoz ships that function as a custom UDF, a binary plus a YAML definition.
Foundry mounts the definition as `functions.yaml`, but ClickHouse's config
glob is `*function.yaml`, singular, so the file never matches and the UDF
never loads. And hiding behind that was a second bug: the definition declares
the quantile argument as `Array(Float64)` while the generated SQL passes a
scalar. Renaming the file, fixing the type and running `SYSTEM RELOAD CONFIG`
fixed p99 queries for good. I filed both upstream as
[SigNoz/foundry#161](https://github.com/SigNoz/foundry/issues/161).

## What worked, what didn't

Worked: OTel auto-instrumentation was genuinely zero-code for my stack; the
trace-to-logs join is the best version of that workflow I have personally
used; and the v5 alert builder's multi-query formulas are more capable than I
expected from a self-hosted tool.

Didn't: the install docs are lagging the Foundry migration quite badly;
ingestion being silently gated on signup cost me my longest debugging session
for the silliest reason; and the UDF packaging bug means histogram quantiles
are broken out of the box on a fresh Foundry install.

Now this might be sounding like a list of complaints, but I feel it is the
opposite. Every one of these detours forced me to understand how the thing
actually works underneath, OpAMP, bucket boundaries, ClickHouse UDFs, and I
came out the other side genuinely liking the tool. All of this was one
evening on an M-series MacBook with 16GB RAM under Colima. Your setup will
differ, but the OpAMP behavior and the Foundry bugs should reproduce
anywhere.

## The one-liner

Self-hosting SigNoz is twenty minutes of casting containers and two hours of
spelunking, and the spelunking is where all the learning lives.

Code for brewlog is [on GitHub](https://github.com/ankurgupta255/brewlog),
SigNoz docs are at [signoz.io/docs](https://signoz.io/docs), OpenTelemetry
Python at [opentelemetry.io](https://opentelemetry.io/docs/languages/python/).
