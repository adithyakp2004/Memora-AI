import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiError } from '../api/client.js'
import { useAuth } from '../auth/AuthContext.jsx'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const SUPPORTED_EXTENSIONS = new Set(['.pdf', '.docx', '.txt'])

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function getExtension(filename) {
  return filename.slice(filename.lastIndexOf('.')).toLowerCase()
}

export function DocumentsPage() {
  const { token } = useAuth()
  const [documents, setDocuments] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [indexingDocumentId, setIndexingDocumentId] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [activeDocument, setActiveDocument] = useState(null)
  const [isReading, setIsReading] = useState(false)

  const loadDocuments = useCallback(async () => {
    setIsLoading(true)
    try {
      const result = await api.documents.list(token)
      setDocuments(result)
      setError('')
    } catch (loadError) {
      setError(
        loadError instanceof ApiError
          ? loadError.message
          : 'Documents could not be loaded. Please try again.',
      )
    } finally {
      setIsLoading(false)
    }
  }, [token])

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  useEffect(() => {
    if (!activeDocument) return undefined

    function closeOnEscape(event) {
      if (event.key === 'Escape') {
        setActiveDocument(null)
      }
    }

    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [activeDocument])

  async function handleUpload(event) {
    event.preventDefault()
    const uploadForm = event.currentTarget
    setError('')
    setNotice('')

    if (!selectedFile) {
      setError('Choose a PDF, DOCX, or TXT file to upload.')
      return
    }

    const extension = getExtension(selectedFile.name)
    if (!SUPPORTED_EXTENSIONS.has(extension)) {
      setError('Only PDF, DOCX, and TXT documents are supported.')
      return
    }
    if (selectedFile.size === 0) {
      setError('Empty files cannot be uploaded.')
      return
    }
    if (selectedFile.size > MAX_FILE_SIZE) {
      setError('The maximum file size is 10 MB.')
      return
    }

    setIsUploading(true)
    try {
      const uploadedDocument = await api.documents.upload(token, selectedFile)
      setDocuments((current) => [uploadedDocument, ...current])
      setSelectedFile(null)
      uploadForm.reset()
      setNotice(`${uploadedDocument.original_filename} was uploaded and processed.`)
    } catch (uploadError) {
      setError(
        uploadError instanceof ApiError
          ? uploadError.message
          : 'The document could not be uploaded. Please try again.',
      )
    } finally {
      setIsUploading(false)
    }
  }

  async function handleView(document) {
    setIsReading(true)
    setError('')
    try {
      const content = await api.documents.content(token, document.id)
      setActiveDocument(content)
    } catch (readError) {
      setError(
        readError instanceof ApiError
          ? readError.message
          : 'The extracted text could not be loaded.',
      )
    } finally {
      setIsReading(false)
    }
  }

  async function handleDelete(document) {
    if (!window.confirm(`Delete "${document.original_filename}"?`)) {
      return
    }

    setError('')
    setNotice('')
    try {
      await api.documents.delete(token, document.id)
      setDocuments((current) =>
        current.filter((item) => item.id !== document.id),
      )
      setNotice(`${document.original_filename} was deleted.`)
    } catch (deleteError) {
      setError(
        deleteError instanceof ApiError
          ? deleteError.message
          : 'The document could not be deleted. Please try again.',
      )
    }
  }

  async function handleReindex(document) {
    setError('')
    setNotice('')
    setIndexingDocumentId(document.id)
    try {
      const updatedDocument = await api.documents.reindex(token, document.id)
      setDocuments((current) =>
        current.map((item) =>
          item.id === updatedDocument.id ? updatedDocument : item,
        ),
      )
      setNotice(`${document.original_filename} was indexed.`)
    } catch (indexError) {
      setError(
        indexError instanceof ApiError
          ? indexError.message
          : 'The document could not be indexed. Please try again.',
      )
    } finally {
      setIndexingDocumentId(null)
    }
  }

  return (
    <main className="workspace documents-workspace">
      <header className="topbar">
        <Link className="brand" to="/app" aria-label="MEMORA dashboard">
          <span className="brand-mark" aria-hidden="true">
            m
          </span>
          <span>memora</span>
        </Link>
        <Link className="text-button" to="/app">
          Back to workspace
        </Link>
        <Link className="text-button" to="/search">
          Semantic search
        </Link>
      </header>

      <section className="documents-heading">
        <p className="eyebrow">Your knowledge library</p>
        <h1 id="documents-heading">Documents</h1>
        <p className="intro">
          Add your own files and keep their extracted text in your private
          workspace.
        </p>
      </section>

      <section className="upload-card" aria-labelledby="upload-heading">
        <div>
          <p className="eyebrow">Add a file</p>
          <h2 id="upload-heading">Bring a document into MEMORA.</h2>
          <p className="connection-message">
            PDF, DOCX, or TXT · Up to 10 MB · Text-based documents only
          </p>
        </div>
        <form className="upload-form" onSubmit={handleUpload}>
          <label className="form-field" htmlFor="document-file">
            <span>Choose a document</span>
            <input
              accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              id="document-file"
              onChange={(event) => {
                setError('')
                setSelectedFile(event.target.files?.[0] ?? null)
              }}
              required
              type="file"
            />
          </label>
          {selectedFile && (
            <p className="selected-file" aria-live="polite">
              {selectedFile.name} · {formatFileSize(selectedFile.size)}
            </p>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="form-notice" role="status">
              {notice}
            </p>
          )}
          <button className="auth-submit upload-submit" disabled={isUploading}>
            {isUploading ? 'Uploading and extracting text…' : 'Upload document'}
          </button>
        </form>
      </section>

      <section className="documents-list-section" aria-labelledby="list-heading">
        <div className="documents-list-heading">
          <div>
            <p className="eyebrow">Your files</p>
            <h2 id="list-heading">Uploaded documents</h2>
          </div>
          <button
            className="retry-button"
            disabled={isLoading}
            onClick={loadDocuments}
            type="button"
          >
            {isLoading ? 'Loading…' : 'Refresh'}
          </button>
        </div>

        {isLoading ? (
          <p className="documents-message" role="status">
            Loading your documents…
          </p>
        ) : documents.length === 0 ? (
          <div className="documents-empty">
            <p className="eyebrow">A fresh start</p>
            <h3>Your library is ready when you are.</h3>
            <p>Upload a PDF, DOCX, or TXT file to see it here.</p>
          </div>
        ) : (
          <ul className="document-list">
            {documents.map((document) => (
              <li className="document-card" key={document.id}>
                <div className="document-card-main">
                  <div className="document-file-icon" aria-hidden="true">
                    {document.file_type.slice(1).toUpperCase()}
                  </div>
                  <div className="document-details">
                    <h3>{document.original_filename}</h3>
                    <p>
                      {formatFileSize(document.file_size)} ·{' '}
                      {formatDate(document.created_at)}
                    </p>
                  </div>
                  <span
                    className={`document-status document-status--${document.processing_status}`}
                  >
                    Text: {document.processing_status}
                  </span>
                  <span
                    className={`document-status document-status--${document.indexing_status}`}
                  >
                    Index: {document.indexing_status}
                  </span>
                </div>
                {document.error_message && (
                  <p className="document-error">{document.error_message}</p>
                )}
                {document.indexing_error && (
                  <p className="document-error">{document.indexing_error}</p>
                )}
                <div className="document-actions">
                  {document.indexing_status !== 'completed' && (
                    <button
                      className="retry-button"
                      disabled={indexingDocumentId !== null}
                      onClick={() => handleReindex(document)}
                      type="button"
                    >
                      {indexingDocumentId === document.id
                        ? 'Indexing…'
                        : 'Retry indexing'}
                    </button>
                  )}
                  <button
                    className="retry-button"
                    disabled={
                      document.processing_status !== 'completed' || isReading
                    }
                    onClick={() => handleView(document)}
                    type="button"
                  >
                    {isReading ? 'Loading text…' : 'View extracted text'}
                  </button>
                  <button
                    className="text-button document-delete"
                    onClick={() => handleDelete(document)}
                    type="button"
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="footer">
        <span>Stored privately in your MEMORA workspace.</span>
        <span>PDF · DOCX · TXT</span>
      </footer>

      {activeDocument && (
        <div
          className="document-dialog-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setActiveDocument(null)
            }
          }}
        >
          <section
            aria-labelledby="document-dialog-heading"
            aria-modal="true"
            className="document-dialog"
            role="dialog"
          >
            <div className="document-dialog-heading">
              <div>
                <p className="eyebrow">Extracted text</p>
                <h2 id="document-dialog-heading">
                  {activeDocument.original_filename}
                </h2>
              </div>
              <button
                aria-label="Close extracted text"
                className="text-button"
                onClick={() => setActiveDocument(null)}
                type="button"
              >
                Close
              </button>
            </div>
            <pre className="document-content">{activeDocument.extracted_text}</pre>
          </section>
        </div>
      )}
    </main>
  )
}
