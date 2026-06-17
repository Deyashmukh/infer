import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DocumentViewer } from '../components/DocumentViewer'
import type { SessionStatus, Document } from '../api'

// react-pdf requires a canvas and PDF.js worker which don't exist in jsdom.
// Mock the react-pdf components for render-gate tests.
vi.mock('react-pdf', () => ({
  Document: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="pdf-document">{children}</div>
  ),
  Page: ({ onRenderSuccess }: { onRenderSuccess?: () => void }) => {
    // Simulate render success to test the latency callback
    onRenderSuccess?.()
    return <div data-testid="pdf-page" />
  },
  pdfjs: { GlobalWorkerOptions: { workerSrc: '' } },
}))

const DOCS: Document[] = [
  { doc_id: 'doc1', name: 'Policy.pdf' },
  { doc_id: 'doc2', name: 'Summary.pdf' },
]

const NON_READY_STATUSES: SessionStatus[] = [
  'STARTING',
  'AWAITING_MFA',
  'VERIFYING_MFA',
  'FETCHING',
  'FAILED',
]

describe('DocumentViewer', () => {
  beforeAll(() => {
    // Silence react-pdf console errors in test output
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
  })

  it.each(NON_READY_STATUSES)(
    'returns null for status %s',
    (status) => {
      const { container } = render(
        <DocumentViewer
          status={status}
          sessionId="sid"
          documents={DOCS}
          mfaSubmitTimestamp={null}
        />,
      )
      expect(container.firstChild).toBeNull()
    },
  )

  it('renders documents when status is READY', () => {
    render(
      <DocumentViewer
        status="READY"
        sessionId="sid"
        documents={DOCS}
        mfaSubmitTimestamp={null}
      />,
    )
    expect(screen.getAllByTestId('pdf-document')).toHaveLength(2)
    expect(screen.getByText('Policy.pdf')).toBeInTheDocument()
    expect(screen.getByText('Summary.pdf')).toBeInTheDocument()
  })

  it('renders a download link per document', () => {
    render(
      <DocumentViewer
        status="READY"
        sessionId="sid"
        documents={DOCS}
        mfaSubmitTimestamp={null}
      />,
    )
    const links = screen.getAllByRole('link', { name: /download/i })
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute('download')
  })

  it('calls onFirstRender with latency when first page renders', () => {
    const onFirstRender = vi.fn()
    const mfaTs = performance.now() - 500 // 500ms ago
    render(
      <DocumentViewer
        status="READY"
        sessionId="sid"
        documents={DOCS}
        mfaSubmitTimestamp={mfaTs}
        onFirstRender={onFirstRender}
      />,
    )
    expect(onFirstRender).toHaveBeenCalledTimes(1)
    const latency = onFirstRender.mock.calls[0][0] as number
    expect(latency).toBeGreaterThan(0)
  })
})
