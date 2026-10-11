import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiError } from '../api/client.js'
import { useAuth } from '../auth/AuthContext.jsx'

export function SearchPage() {
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [indexedChunkCount, setIndexedChunkCount] = useState(null)
  const [minimumSimilarity, setMinimumSimilarity] = useState(null)
  const [error, setError] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [hasSearched, setHasSearched] = useState(false)

  async function handleSearch(event) {
    event.preventDefault()
    const normalizedQuery = query.trim()
    if (!normalizedQuery) {
      setError('Enter a question or a few keywords to search your documents.')
      setResults([])
      setHasSearched(false)
      return
    }

    setError('')
    setIsSearching(true)
    setHasSearched(false)
    try {
      const response = await api.search(token, normalizedQuery, 5)
      setResults(response.results)
      setSubmittedQuery(response.query)
      setIndexedChunkCount(response.indexed_chunk_count ?? null)
      setMinimumSimilarity(response.minimum_similarity ?? null)
      setHasSearched(true)
    } catch (searchError) {
      setError(
        searchError instanceof ApiError
          ? searchError.message
          : 'Semantic search could not be completed. Please try again.',
      )
      setResults([])
      setIndexedChunkCount(null)
      setMinimumSimilarity(null)
    } finally {
      setIsSearching(false)
    }
  }

  return (
    <main className="workspace search-workspace">
      <header className="topbar">
        <Link className="brand" to="/app" aria-label="MEMORA dashboard">
          <span className="brand-mark" aria-hidden="true">
            m
          </span>
          <span>memora</span>
        </Link>
        <nav className="search-navigation" aria-label="Workspace">
          <Link className="text-button" to="/documents">
            Documents
          </Link>
          <Link className="text-button" to="/app">
            Back to workspace
          </Link>
        </nav>
      </header>

      <section className="documents-heading">
        <p className="eyebrow">Explore your library</p>
        <h1 id="search-heading">Semantic search</h1>
        <p className="intro">
          Find passages by meaning across your indexed documents.
        </p>
      </section>

      <section className="search-card" aria-labelledby="search-heading">
        <form className="semantic-search-form" onSubmit={handleSearch}>
          <label className="form-field" htmlFor="semantic-query">
            <span>What would you like to find?</span>
            <textarea
              id="semantic-query"
              maxLength={2000}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="For example: What are the key project deadlines?"
              rows={3}
              value={query}
            />
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="auth-submit search-submit" disabled={isSearching}>
            {isSearching ? 'Searching your documents…' : 'Search documents'}
          </button>
        </form>
      </section>

      <section className="search-results-section" aria-live="polite">
        {isSearching ? (
          <p className="documents-message" role="status">
            Searching your indexed documents…
          </p>
        ) : hasSearched && results.length === 0 ? (
          <div className="documents-empty">
            {indexedChunkCount === 0 ? (
              <>
                <p className="eyebrow">No indexed passages</p>
                <h2>No indexed document passages are available.</h2>
                <p>Index a document before searching your library.</p>
              </>
            ) : indexedChunkCount > 0 ? (
              <>
                <p className="eyebrow">No qualifying matches</p>
                <h2>No passages met the minimum similarity.</h2>
                <p>
                  Try different wording. The current minimum cosine similarity
                  is{' '}
                  {minimumSimilarity == null
                    ? 'configured by the server'
                    : minimumSimilarity.toFixed(2)}
                  .
                </p>
              </>
            ) : (
              <>
                <p className="eyebrow">No matches yet</p>
                <h2>No relevant passages were found.</h2>
                <p>Try different wording or add and index more documents.</p>
              </>
            )}
          </div>
        ) : hasSearched ? (
          <>
            <div className="documents-list-heading">
              <div>
                <p className="eyebrow">Search results</p>
                <h2>{results.length} matching passages</h2>
                <p className="connection-message">
                  Results for “{submittedQuery}”
                </p>
              </div>
            </div>
            <ol className="search-result-list">
              {results.map((result) => (
                <li className="search-result-card" key={result.chunk_id}>
                  <div className="search-result-heading">
                    <div>
                      <p className="eyebrow">
                        Chunk {result.chunk_index + 1}
                        {result.page_start != null
                          ? ` · Page ${result.page_start}${result.page_end != null && result.page_end !== result.page_start ? `–${result.page_end}` : ''}`
                          : ''}
                      </p>
                      <h3>{result.document_filename}</h3>
                    </div>
                    <span className="similarity-score">
                      Cosine similarity {result.cosine_similarity.toFixed(2)}
                    </span>
                  </div>
                  <p className="search-passage">{result.passage}</p>
                </li>
              ))}
            </ol>
          </>
        ) : null}
      </section>

      <footer className="footer">
        <span>Search runs locally against your private indexed documents.</span>
        <span>Cosine similarity · Top 5</span>
      </footer>
    </main>
  )
}
