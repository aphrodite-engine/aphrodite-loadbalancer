# Aphrodite Load Balancer

A simple, no-nonsense load balancer for [Aphrodite Engine](https://github.com/aphrodite-engine/aphrodite-engine). Designed for balancing requests between multiple Aphrodite Engine instances. It performs round-robin load balancing to provide equal distribution of requests across all endpoints. You can also specify weights for each endpoint to control the distribution of requests, or specific paths to be routed to a specific endpoint.

You may also use this with any OpenAI-compatible API endpoint, not just Aphrodite Engine.

## Installation

### From Source

```bash
git clone https://github.com/aphrodite-engine/aphrodite-loadbalancer.git
cd aphrodite-loadbalancer
pip install -e .
```

### From PyPI
Coming soon.


## Usage
Assuming you have two Aphrodite instances running on `https://example_1.com` and `https://example_2.com`, create a YAML configuration file `config.yaml` with the following content:

```yaml
endpoints:
  - url: https://example_1.com
  - url: https://example_2.com
```

Then run the load balancer with:

```bash
aphrodite-loadbalancer --config config.yaml
```

### Configuration

The loadbalancer supports the following configuration options:

- Weighted round-robin balancing:

This enables you to specify weights for each endpoint to control the distribution of requests. Essentially, the more weight an endpoint has, the more requests it will receive.

Example:

```yaml
endpoints:
  - url: https://example_1.com
    weight: 1
  - url: https://example_2.com
    weight: 2
```

- Path routing:

You may specify specific paths to be routed to a specific endpoint. This is useful if you want a specific endpoint to handle tokenization requests, and another completion requests, and so on.

Example:

```yaml
endpoints:
  - url: "http://localhost:2242"
    weight: 2
    paths: ["/v1/completions"]
  - url: "http://localhost:2243"
    weight: 1
    paths: ["/v1/chat/completions"]
  - url: "http://localhost:2244"
    paths: ["/v1/tokenize", "/v1/detokenize"]
    weight: 1
```


## Development

Fork the repository and clone it to your local machine, then check out a new branch for your changes.

```bash
git clone https://github.com/your-fork/aphrodite-loadbalancer.git
cd aphrodite-loadbalancer
git checkout -b my-new-feature
```

Install the development dependencies:

```bash
pip install -e .[test]
```

Commit your changes and push to your fork:

```bash
git add .
git commit -m "My new feature"
git push origin my-new-feature
```

Run tests:

```bash
pytest tests -v
```


