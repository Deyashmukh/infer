import { Document, Page } from 'react-pdf'
import type { SessionStatus, Document as Doc } from '../api'
import { documentUrl } from '../api'

interface DocumentViewerProps {
  status: SessionStatus
  sessionId: string
  documents: Doc[]
  /** performance.now() timestamp recorded when MFA was submitted */
  mfaSubmitTimestamp: number | null
  onFirstRender?: (latencyMs: number) => void
}

export function DocumentViewer({
  status,
  sessionId,
  documents,
  mfaSubmitTimestamp,
  onFirstRender,
}: DocumentViewerProps) {
  if (status !== 'READY') return null

  function handleFirstRenderSuccess() {
    if (mfaSubmitTimestamp !== null) {
      const latencyMs = performance.now() - mfaSubmitTimestamp
      onFirstRender?.(latencyMs)
    }
  }

  return (
    <div className="document-viewer">
      <h2>Your documents</h2>
      {documents.map((doc, idx) => (
        <div key={doc.doc_id} className="document-item">
          <div className="document-header">
            <span className="document-name">{doc.name}</span>
            <a
              href={documentUrl(sessionId, doc.doc_id)}
              download={doc.name}
              className="download-link"
            >
              Download
            </a>
          </div>
          <Document
            file={documentUrl(sessionId, doc.doc_id)}
            className="pdf-document"
          >
            <Page
              pageNumber={1}
              onRenderSuccess={idx === 0 ? handleFirstRenderSuccess : undefined}
            />
          </Document>
        </div>
      ))}
    </div>
  )
}
