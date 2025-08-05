# TradeMon: AI-Powered Stock Analysis

TradeMon is a scalable stock analysis tool that uses machine learning and real-time internet data to predict market trends. It leverages a local large language model to search for relevant information, analyze sentiment, and extract financial metrics. These features are then passed to a TensorFlow classifier for market prediction.

## Architecture Overview
TradeMon is fully containerized with Docker for ease of deployment and scalability.
API keys for Brave Search API and AlphaVantageAPI are needed (keys.env).

##### Search & Data Collection
Uses the Brave Search API to gather information from the web. Daily stock prices are pulled from the AlphaVantage API.

##### Language Model (LLM)
A local LLM runs via llama.cpp for efficient inference. For lower-spec machines, you can optionally switch to the OpenAI API.

##### Machine Learning Backend
A TensorFlow-based classifier ingests structured and unstructured data to produce buy/sell signals.

##### Caching
Redis is used to cache processed data and avoid redundant computations.

##### Features
- Plug-and-play containerized infrastructure with Docker.
- Real-time web search and news sentiment analysis.
- Scalable pipeline for adding new data sources or ML models.

