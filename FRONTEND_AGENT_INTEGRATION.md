# Frontend Agent Integration

## Current Backend Contract

There are now two reprocess paths:

- Use stored reprocess when staff wants to rerun the existing uploaded file as-is.
- Use reprocess upload when staff wants to replace the bytes for an existing failed or incorrect transcript and rerun parsing through the `DocumentAgent`.

### Reprocess Stored File

- Method: `POST`
- URL: `/api/v1/documents/{documentId}/reprocess`
- Headers:
  - `Authorization: Bearer <access_token>`
  - `X-Tenant-Id: <tenant_id>`

Example success response:

```json
{
  "success": true,
  "status": "processing",
  "detail": "Document queued for reprocessing.",
  "documentId": "3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
  "documentUploadId": "3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
  "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "agentRunId": "8c2f6a8e-bc13-4d49-8fb1-5f1a9ce2f5cb"
}
```

This endpoint now uses the stored original file bytes in backend storage and returns the same polling identifiers as the upload-replacement flow.

### Start Reprocess

- Method: `POST`
- URL: `/api/v1/documents/{documentId}/reprocess-upload`
- Headers:
  - `Authorization: Bearer <access_token>`
  - `X-Tenant-Id: <tenant_id>`
- Content type: `multipart/form-data`
- Form fields:
  - `file`: required
  - `document_type`: optional, default `auto`
  - `use_bedrock`: optional, default `true`

Example success response:

```json
{
  "success": true,
  "status": "processing",
  "detail": "Document queued for agent reprocessing.",
  "documentId": "3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
  "documentUploadId": "3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
  "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "agentRunId": "8c2f6a8e-bc13-4d49-8fb1-5f1a9ce2f5cb"
}
```

### Poll Agent Run

- Method: `GET`
- URL: `/api/v1/agent-runs/{agentRunId}`

Example response:

```json
{
  "runId": "8c2f6a8e-bc13-4d49-8fb1-5f1a9ce2f5cb",
  "agentName": "document_agent",
  "agentType": "document",
  "status": "completed",
  "triggerEvent": "manual_reprocess_upload",
  "studentId": "b33b4836-25af-42cf-9109-2917077ad4ad",
  "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "actorUserId": "f7d23f85-7c43-48aa-bb88-8ebc0edb0404",
  "correlationId": "document-reprocess:3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
  "error": null,
  "startedAt": "2026-05-05T18:11:10Z",
  "completedAt": "2026-05-05T18:11:18Z"
}
```

Valid `status` values to handle right now:

- `queued`
- `running`
- `completed`
- `failed`

### Poll Agent Actions

- Method: `GET`
- URL: `/api/v1/agent-runs/{agentRunId}/actions`

Example response:

```json
{
  "runId": "8c2f6a8e-bc13-4d49-8fb1-5f1a9ce2f5cb",
  "items": [
    {
      "actionId": "9f552f2d-eec2-4a7b-a3a3-113efa0baad0",
      "actionType": "parse_transcript",
      "toolName": "parse_transcript",
      "status": "completed",
      "studentId": "b33b4836-25af-42cf-9109-2917077ad4ad",
      "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
      "error": null,
      "startedAt": "2026-05-05T18:11:10Z",
      "completedAt": "2026-05-05T18:11:15Z",
      "input": {
        "filename": "replacement.pdf"
      },
      "output": {
        "courses": 31
      }
    }
  ]
}
```

### Poll Transcript Status

The frontend should also poll the existing transcript status endpoint:

- Method: `GET`
- URL: `/api/v1/transcripts/uploads/{transcriptId}/status`

Use this to drive the existing transcript-processing UI state. The agent run tells you what the agent is doing; the transcript status tells you whether persistence finished.

### Load Exception Summary

- Method: `GET`
- URL: `/api/v1/documents/{documentId}/exception-summary`

Example response:

```json
{
  "documentId": "3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
  "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "studentId": "2026-18473",
  "studentName": "Mira Holloway",
  "documentStatus": "failed",
  "transcriptStatus": "failed",
  "parserConfidence": null,
  "issueType": "processing_failure",
  "issueLabel": "No courses were extracted from transcript.",
  "issueStatus": "course_mapping_failed",
  "suggestedAction": "Retry document processing with the same file.",
  "failureCode": "course_mapping_failed",
  "failureMessage": "No courses were extracted from transcript.",
  "createdAt": "2026-05-05T18:11:10Z",
  "updatedAt": "2026-05-05T18:11:18Z",
  "latestRun": {
    "runId": "8c2f6a8e-bc13-4d49-8fb1-5f1a9ce2f5cb",
    "agentName": "document_agent",
    "status": "failed",
    "triggerEvent": "stored_reprocess",
    "error": "No courses were extracted from transcript.",
    "startedAt": "2026-05-05T18:11:10Z",
    "completedAt": "2026-05-05T18:11:18Z"
  },
  "recentActions": [
    {
      "actionId": "9f552f2d-eec2-4a7b-a3a3-113efa0baad0",
      "actionType": "parse_transcript",
      "toolName": "parse_transcript",
      "status": "failed",
      "error": "No courses were extracted from transcript.",
      "startedAt": "2026-05-05T18:11:10Z",
      "completedAt": "2026-05-05T18:11:18Z",
      "input": {
        "filename": "replacement.pdf"
      },
      "output": {}
    }
  ]
}
```

## Recommended Frontend Behavior

- Prefer the enriched `/api/v1/documents/exceptions` list for the queue view. Each item now includes `reason`, `suggestedAction`, `transcriptStatus`, `documentStatus`, and `latestRunStatus`.
- If the user wants to rerun the same uploaded file, call `POST /documents/{documentId}/reprocess`.
- If the user wants to replace the file, show a file picker and call `POST /documents/{documentId}/reprocess-upload`.
- Store `agentRunId` and `transcriptId` from the response.
- Poll `GET /agent-runs/{agentRunId}` every 2 to 3 seconds until `completed` or `failed`.
- Optionally call `GET /agent-runs/{agentRunId}/actions` when the run fails or when the user opens a details drawer.
- Prefer `GET /documents/{documentId}/exception-summary` for the exception drawer or details panel.
- Poll `GET /transcripts/uploads/{transcriptId}/status` on the same cadence.
- Treat the operation as successful only when:
  - agent run status is `completed`
  - transcript status is `completed`
- Treat the operation as failed if either endpoint reports `failed`.
- Show the backend `error` or `detail` directly in the document exception UI.
