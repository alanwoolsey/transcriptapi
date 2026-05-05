# Frontend Agent Integration

## Current Backend Contract

### Backend Implementation Note

Transcript extraction, persistence, student context lookup, and checklist linking are now routed through backend document-agent tool adapters. Successful runs can expose `parse_transcript` / `transcript_parsed`, `complete_processing_upload` / `transcript_persisted`, `lookup_student_context` / `student_context_loaded`, and `link_transcript_checklist_item` / `checklist_item_linked`. Failed processing records `fail_processing_upload` with `document_processing_failed` when the transcript upload is marked failed.

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
  "completedAt": "2026-05-05T18:11:18Z",
  "result": {
    "status": "completed",
    "code": "transcript_processed",
    "message": "Transcript parsed successfully.",
    "error": null,
    "metrics": {
      "courses": 31,
      "use_bedrock": true
    },
    "artifacts": {
      "documentId": "3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
      "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84"
    }
  }
}
```

Valid `status` values to handle right now:

- `queued`
- `running`
- `completed`
- `failed`

When available, use `result.code` as the canonical backend outcome:

- `transcript_processed`
- `document_processing_failed`

and use `result.message` / `result.error` directly in the UI before falling back to lower-level action data.

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
        "result": {
          "status": "completed",
          "code": "transcript_parsed",
          "message": "Transcript parsing completed.",
          "error": null,
          "metrics": {
            "courses": 31,
            "use_bedrock": true
          },
          "artifacts": {
            "documentId": "3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
            "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84"
          }
        },
        "input": {
          "filename": "replacement.pdf"
        },
        "output": {
          "status": "completed",
          "code": "transcript_parsed",
          "message": "Transcript parsing completed.",
          "error": null,
          "metrics": {
            "courses": 31,
            "use_bedrock": true
          },
          "artifacts": {
            "documentId": "3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
            "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84"
          }
        }
      }
    ]
  }
  ```

When available, use `items[n].result` as the normalized step summary. Useful action result codes now include:

- `transcript_parsed`
- `transcript_persisted`
- `student_context_loaded`
- `checklist_item_linked`
- `student_context_unavailable`
- `document_context_unavailable`
- `document_processing_failed`

Useful document action tool names now include:

- `parse_transcript`
- `complete_processing_upload`
- `lookup_student_context`
- `link_transcript_checklist_item`
- `fail_processing_upload`

Action `status` can also be `skipped` for optional context/linking actions when the backend does not have enough student or document context. A skipped context/linking action should not be treated as a failed reprocess if the agent run and transcript status are both `completed`.

### Poll Transcript Status

The frontend should also poll the existing transcript status endpoint:

- Method: `GET`
- URL: `/api/v1/transcripts/uploads/{transcriptId}/status`

Use this to drive the existing transcript-processing UI state. The agent run tells you what the agent is doing; the transcript status tells you whether persistence finished.

### Load Exception Summary

- Method: `GET`
- URL: `/api/v1/documents/{documentId}/exception-summary`

This endpoint is now a compatibility summary layered on the same backend source as `GET /documents/{documentId}/run-details`.

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
      "actionType": "fail_transcript_processing",
      "toolName": "fail_processing_upload",
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

### Load Document Run Details

- Method: `GET`
- URL: `/api/v1/documents/{documentId}/run-details`

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
  "latestFailure": {
    "code": "course_mapping_failed",
    "message": "No courses were extracted from transcript.",
    "createdAt": "2026-05-05T18:11:10Z",
    "updatedAt": "2026-05-05T18:11:10Z"
  },
  "run": {
    "runId": "8c2f6a8e-bc13-4d49-8fb1-5f1a9ce2f5cb",
    "agentName": "document_agent",
    "agentType": "document",
    "status": "failed",
    "triggerEvent": "stored_reprocess",
    "studentId": "2026-18473",
    "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
    "actorUserId": "f7d23f85-7c43-48aa-bb88-8ebc0edb0404",
    "correlationId": "document-reprocess:3d1f5f64-8f25-4a79-bd8d-5a7dc8b5c6cc",
    "error": "No courses were extracted from transcript.",
    "startedAt": "2026-05-05T18:11:10Z",
    "completedAt": "2026-05-05T18:11:18Z",
    "result": {
      "status": "failed",
      "code": "document_processing_failed",
      "message": "Transcript processing failed.",
      "error": "No courses were extracted from transcript.",
      "metrics": {
        "use_bedrock": true
      },
      "artifacts": {
        "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84"
      }
    }
  },
  "actions": [
    {
      "actionId": "9f552f2d-eec2-4a7b-a3a3-113efa0baad0",
      "actionType": "fail_transcript_processing",
      "toolName": "fail_processing_upload",
      "status": "failed",
      "studentId": "2026-18473",
      "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
      "error": "No courses were extracted from transcript.",
      "startedAt": "2026-05-05T18:11:10Z",
      "completedAt": "2026-05-05T18:11:18Z",
      "result": {
        "status": "failed",
        "code": "document_processing_failed",
        "message": "Transcript processing failed.",
        "error": "No courses were extracted from transcript.",
        "metrics": {
          "use_bedrock": true
        },
        "artifacts": {
          "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84"
        }
      },
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
- Prefer `agentRun.result` as the primary summary of what happened.
- Optionally call `GET /agent-runs/{agentRunId}/actions` when the run fails or when the user opens a details drawer.
- Prefer `action.result` over raw `action.output` when rendering per-step status.
- Prefer `GET /documents/{documentId}/run-details` for the exception drawer or details panel.
- Keep `GET /documents/{documentId}/exception-summary` only for issue labeling and suggested-action text if the drawer still uses those fields.
- Poll `GET /transcripts/uploads/{transcriptId}/status` on the same cadence.
- Treat the operation as successful only when:
  - agent run status is `completed`
  - transcript status is `completed`
- Treat the operation as failed if either endpoint reports `failed`.
- Show the backend `error` or `detail` directly in the document exception UI.

## Decision Contract

The first `decision_agent` slice is explicit and on-demand. It does not replace the existing decision packet APIs; it adds a normalized recommendation run and read model on top of them.

Decision packet assembly is now routed through the backend `assemble_decision_context` tool adapter. Readiness, trust status, and supporting evidence are also exposed to the DecisionAgent through backend tool adapters. No frontend request/response changes are required for this slice; continue to render `assemble_decision_context` / `decision_context_assembled` action results as documented below.

### Generate Decision Recommendation

- Method: `POST`
- URL: `/api/v1/decisions/{decisionId}/recommendation`

Example response:

```json
{
  "decisionId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "agentRunId": "run-1",
  "recommendation": {
    "fit": 92,
    "creditEstimate": 38,
    "reason": "Explainable rationale text",
    "confidence": 96,
    "rationale": [
      "Explainable rationale text",
      "Parser confidence is 96%.",
      "No active trust signals are blocking review."
    ]
  },
  "status": "completed"
}
```

This endpoint creates or reuses the underlying decision packet, records a normalized `decision_agent` run, and returns the current recommendation plus `agentRunId`.
`recommendation.confidence` is a backend-derived 0 to 100 confidence score for the recommendation. `recommendation.rationale` is an ordered list of evidence and trust reasons supporting the recommendation.

### Review Decision Recommendation

- Method: `POST`
- URL: `/api/v1/decisions/{decisionId}/review`
- Body:

```json
{
  "action": "accept_recommendation",
  "note": "Recommendation accepted after manual review."
}
```

Valid `action` values right now:

- `accept_recommendation`
- `request_evidence`

Example response:

```json
{
  "id": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "action": "accept_recommendation",
  "status": "Approved",
  "snapshotVersion": "4d0f13d56a1c2b33",
  "updatedAt": "2026-05-05T18:12:00Z"
}
```

This endpoint applies the backend-owned review state transition for the current decision packet instead of forcing the frontend to map recommendation acceptance into status changes itself. It also returns the persisted `snapshotVersion` for the exact assembled decision context that was reviewed.

### Load Decision Snapshot

- Method: `GET`
- URL: `/api/v1/decisions/{decisionId}/snapshot`

Example response:

```json
{
  "decisionId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "status": "Draft",
  "readiness": "Ready for review",
  "student": {
    "id": "student-1",
    "name": "Avery Carter",
    "email": "avery@example.com",
    "externalId": "STU-10441"
  },
  "program": {
    "id": null,
    "name": "Nursing transfer review"
  },
  "recommendation": {
    "fit": 92,
    "creditEstimate": 38,
    "reason": "Explainable rationale text",
    "confidence": 96,
    "rationale": [
      "Explainable rationale text",
      "Parser confidence is 96%.",
      "No active trust signals are blocking review."
    ]
  },
  "evidence": {
    "institution": "Harbor Gate University",
    "gpa": 3.42,
    "creditsEarned": 42,
    "parserConfidence": 0.96,
    "documentCount": 3
  },
  "trust": {
    "status": "Clear",
    "signals": []
  }
}
```

Use this when the frontend needs one assembled decision packet payload without depending on agent-run history.

### Load Decision Agent Details

- Method: `GET`
- URL: `/api/v1/decisions/{decisionId}/agent-details`

Example response:

```json
{
  "decisionId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "student": {
    "id": "student-1",
    "name": "Avery Carter",
    "email": "avery@example.com",
    "externalId": "STU-10441"
  },
  "program": {
    "id": null,
    "name": "Nursing transfer review"
  },
  "recommendation": {
    "fit": 92,
    "creditEstimate": 38,
    "reason": "Explainable rationale text",
    "confidence": 96,
    "rationale": [
      "Explainable rationale text",
      "Parser confidence is 96%.",
      "No active trust signals are blocking review."
    ]
  },
  "lastReviewedSnapshot": {
    "action": "accept_recommendation",
    "snapshotVersion": "4d0f13d56a1c2b33",
    "reviewedAt": "2026-05-05T18:12:00Z",
    "reviewedByUserId": "user-1",
    "snapshot": {
      "decisionId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
      "status": "Draft",
      "readiness": "Ready for review",
      "student": {
        "id": "student-1",
        "name": "Avery Carter",
        "email": "avery@example.com",
        "externalId": "STU-10441"
      },
      "program": {
        "id": null,
        "name": "Nursing transfer review"
      },
      "recommendation": {
        "fit": 92,
        "creditEstimate": 38,
        "reason": "Explainable rationale text",
        "confidence": 96,
        "rationale": [
          "Explainable rationale text",
          "Parser confidence is 96%.",
          "No active trust signals are blocking review."
        ]
      },
      "evidence": {
        "institution": "Harbor Gate University",
        "gpa": 3.42,
        "creditsEarned": 42,
        "parserConfidence": 0.96,
        "documentCount": 3
      },
      "trust": {
        "status": "Clear",
        "signals": []
      }
    }
  },
  "latestRun": {
    "runId": "run-1",
    "agentName": "decision_agent",
    "agentType": "decision",
    "status": "completed",
    "triggerEvent": "manual_recommendation",
    "studentId": "student-1",
    "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
    "actorUserId": "user-1",
    "correlationId": "decision-recommend:1",
    "error": null,
    "startedAt": "2026-05-05T18:11:10Z",
    "completedAt": "2026-05-05T18:11:12Z",
    "result": {
      "status": "completed",
      "code": "decision_recommendation_generated",
      "message": "Decision recommendation generated.",
      "error": null,
      "metrics": {
        "status": "Draft",
        "readiness": "Ready for review",
        "fit": 92,
        "creditEstimate": 38,
        "recommendationConfidence": 96,
        "trustStatus": "Clear",
        "trustSignalCount": 0,
        "activeTrustSignalCount": 0,
        "documentCount": 3
      },
      "artifacts": {
        "decisionId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
        "studentId": "student-1",
        "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
        "readinessReason": "Explainable rationale text",
        "institution": "Harbor Gate University",
        "gpa": 3.42,
        "creditsEarned": 42,
        "parserConfidence": 0.96,
        "recommendationReason": "Explainable rationale text",
        "recommendationRationale": [
          "Explainable rationale text",
          "Parser confidence is 96%.",
          "No active trust signals are blocking review."
        ]
      }
    }
  },
  "actions": [
    {
      "actionId": "action-0",
      "actionType": "assemble_decision_context",
      "toolName": "assemble_decision_context",
      "status": "completed",
      "studentId": "student-1",
      "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
      "error": null,
      "startedAt": "2026-05-05T18:11:10Z",
      "completedAt": "2026-05-05T18:11:11Z",
      "result": {
        "status": "completed",
        "code": "decision_context_assembled",
        "message": "Decision context assembled.",
        "error": null,
        "metrics": {
          "status": "Draft",
          "readiness": "Ready for review",
          "trustStatus": "Clear",
          "trustSignalCount": 0,
          "activeTrustSignalCount": 0,
          "documentCount": 3
        },
        "artifacts": {
          "decisionId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
          "studentId": "student-1",
          "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
          "readinessReason": "Explainable rationale text",
          "institution": "Harbor Gate University",
          "gpa": 3.42,
          "creditsEarned": 42,
          "parserConfidence": 0.96
        }
      },
      "input": {},
      "output": {}
    },
    {
      "actionId": "action-1",
      "actionType": "generate_decision_recommendation",
      "toolName": "generate_decision_recommendation",
      "status": "completed",
      "studentId": "student-1",
      "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
      "error": null,
      "startedAt": "2026-05-05T18:11:10Z",
      "completedAt": "2026-05-05T18:11:12Z",
      "result": {
        "status": "completed",
        "code": "decision_recommendation_generated",
        "message": "Decision recommendation generated.",
        "error": null,
        "metrics": {
          "status": "Draft",
          "readiness": "Ready for review",
          "fit": 92,
          "creditEstimate": 38,
          "recommendationConfidence": 96,
          "trustStatus": "Clear",
          "trustSignalCount": 0,
          "activeTrustSignalCount": 0,
          "documentCount": 3
        },
        "artifacts": {
          "decisionId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
          "studentId": "student-1",
          "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
          "readinessReason": "Explainable rationale text",
          "institution": "Harbor Gate University",
          "gpa": 3.42,
          "creditsEarned": 42,
          "parserConfidence": 0.96,
          "recommendationReason": "Explainable rationale text",
          "recommendationRationale": [
            "Explainable rationale text",
            "Parser confidence is 96%.",
            "No active trust signals are blocking review."
          ]
        }
      },
      "input": {},
      "output": {}
    }
  ]
}
```

### Recommended Decision Behavior

- Keep using the existing decision packet endpoints for assignment, notes, and timeline.
- Use `GET /api/v1/decisions/{decisionId}/snapshot` when the UI needs the assembled decision packet/evidence/trust payload directly.
- Use `POST /api/v1/decisions/{decisionId}/recommendation` when a reviewer wants an explicit agent-generated recommendation run.
- Use `POST /api/v1/decisions/{decisionId}/review` when a reviewer wants to accept the current recommendation or send it back for more evidence.
- Store `agentRunId` from that response if you want to poll the generic `/api/v1/agent-runs/{agentRunId}` endpoint too.
- Store `snapshotVersion` from the review response if the UI needs to show which recommendation snapshot was accepted or sent back.
- Prefer `GET /api/v1/decisions/{decisionId}/agent-details` for the decision recommendation drawer or side panel.
- Use `lastReviewedSnapshot` from `GET /api/v1/decisions/{decisionId}/agent-details` when the UI needs to show the exact snapshot payload that was previously accepted or sent back.
- Use `action = "accept_recommendation"` to move the packet to `Approved`.
- Use `action = "request_evidence"` to move the packet to `Needs evidence`.
- Use `latestRun.result` as the top-level decision-agent outcome.
- Use `recommendation.confidence` and `recommendation.rationale` when showing the recommendation strength and explainable support in the decision drawer.
- Use `actions[n].result` for step-level recommendation history.
- Useful decision result codes currently include:
  - `decision_context_assembled`
  - `decision_readiness_loaded`
  - `decision_trust_status_loaded`
  - `decision_supporting_evidence_loaded`
  - `decision_recommendation_generated`

## Trust Contract

Manual trust actions like match confirm/reject and quarantine/release now create normalized `trust_agent` runs and actions.

### List Trust Cases

- Method: `GET`
- URL: `/api/v1/trust/cases`

Example response item:

```json
{
  "id": "TRUST-01",
  "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "studentId": "2026-18473",
  "student": "Mira Holloway",
  "documentId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "document": "Official transcript",
  "severity": "High",
  "signal": "Manual quarantine",
  "evidence": "Document quarantined by reviewer.",
  "status": "Open",
  "trustBlocked": true,
  "latestRunStatus": "completed",
  "latestResultCode": "trust_document_quarantined",
  "owner": {
    "id": "user-1",
    "name": "Taylor Reed"
  },
  "openedAt": "2026-05-05T18:11:10Z",
  "summary": {
    "riskLevel": "high",
    "summary": "Manual quarantine is open. Student progression is currently blocked.",
    "rationale": "Document quarantined by reviewer. Latest trust-agent outcome: trust_document_quarantined. Owner: Taylor Reed.",
    "recommendedAction": "Review the trust signal and decide whether progression should remain blocked.",
    "signals": ["Manual quarantine", "High", "Open"]
  }
}
```

Use this list for the trust queue. It now includes:

- `transcriptId`
- `trustBlocked`
- `latestRunStatus`
- `latestResultCode`
- `owner`
- `summary`

### Load Trust Case Details

- Method: `GET`
- URL: `/api/v1/trust/transcripts/{transcriptId}/details`

Example response:

```json
{
  "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
  "studentId": "2026-18473",
  "student": "Mira Holloway",
  "document": "Official transcript",
  "severity": "High",
  "signal": "Manual quarantine",
  "evidence": "Document quarantined by reviewer.",
  "status": "Open",
  "trustBlocked": true,
  "owner": {
    "id": "user-1",
    "name": "Taylor Reed"
  },
  "openedAt": "2026-05-05T18:11:10Z",
  "summary": {
    "riskLevel": "high",
    "summary": "Manual quarantine is open. Student progression is currently blocked.",
    "rationale": "Document quarantined by reviewer. Latest trust-agent outcome: trust_document_quarantined. Owner: Taylor Reed.",
    "recommendedAction": "Review the trust signal and decide whether progression should remain blocked.",
    "signals": ["Manual quarantine", "High", "Open"]
  },
  "latestRun": {
    "runId": "run-1",
    "agentName": "trust_agent",
    "agentType": "trust",
    "status": "completed",
    "triggerEvent": "manual_quarantine",
    "studentId": "2026-18473",
    "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
    "actorUserId": "user-1",
    "correlationId": "trust-quarantine:doc-1",
    "error": null,
    "startedAt": "2026-05-05T18:11:10Z",
    "completedAt": "2026-05-05T18:11:12Z",
    "result": {
      "status": "completed",
      "code": "trust_document_quarantined",
      "message": "Document quarantined.",
      "error": null,
      "metrics": {},
      "artifacts": {
        "documentId": "doc-1",
        "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84"
      }
    }
  },
  "actions": [
    {
      "actionId": "action-1",
      "actionType": "quarantine_document",
      "toolName": "quarantine_document",
      "status": "completed",
      "studentId": "2026-18473",
      "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84",
      "error": null,
      "startedAt": "2026-05-05T18:11:10Z",
      "completedAt": "2026-05-05T18:11:12Z",
      "result": {
        "status": "completed",
        "code": "trust_document_quarantined",
        "message": "Document quarantined.",
        "error": null,
        "metrics": {},
        "artifacts": {
          "documentId": "doc-1",
          "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84"
        }
      },
      "input": {
        "action": "quarantine_document"
      },
      "output": {
        "status": "completed",
        "code": "trust_document_quarantined",
        "message": "Document quarantined.",
        "error": null,
        "metrics": {},
        "artifacts": {
          "documentId": "doc-1",
          "transcriptId": "4d067228-d3b8-4cc4-93ab-1a5436dbfe84"
        }
      }
    }
  ]
}
```

### Block Trust Case

- Method: `POST`
- URL: `/api/v1/trust/transcripts/{transcriptId}/block`
- Body:

```json
{
  "note": "Hold until issuer is verified."
}
```

Example response:

```json
{
  "success": true,
  "status": "blocked",
  "detail": "Trust case blocked."
}
```

### Unblock Trust Case

- Method: `POST`
- URL: `/api/v1/trust/transcripts/{transcriptId}/unblock`
- Body:

```json
{
  "note": "Cleared for progression."
}
```

Example response:

```json
{
  "success": true,
  "status": "unblocked",
  "detail": "Trust case unblocked."
}
```

### Resolve Trust Case

- Method: `POST`
- URL: `/api/v1/trust/transcripts/{transcriptId}/resolve`
- Body:

```json
{
  "note": "False positive after manual review."
}
```

Example response:

```json
{
  "success": true,
  "status": "resolved",
  "detail": "Trust case resolved."
}
```

### Escalate Trust Case

- Method: `POST`
- URL: `/api/v1/trust/transcripts/{transcriptId}/escalate`
- Body:

```json
{
  "note": "Needs secondary trust review."
}
```

Example response:

```json
{
  "success": true,
  "status": "escalated",
  "detail": "Trust case escalated."
}
```

### Assign Trust Case

- Method: `POST`
- URL: `/api/v1/trust/transcripts/{transcriptId}/assign`
- Body:

```json
{
  "userId": "f7d23f85-7c43-48aa-bb88-8ebc0edb0404",
  "note": "Assigning for deeper investigation."
}
```

Example response:

```json
{
  "success": true,
  "status": "assigned",
  "detail": "Trust case assigned."
}
```

### Recommended Trust Behavior

- TrustAgent now has backend tool adapters for identity match context, trust flags, document history, and trust case create/escalate/resolve operations. No frontend request/response changes are required for this slice; continue to consume the trust queue, details, and action endpoints below.
- Use `GET /api/v1/trust/cases` for the queue.
- Use `trustBlocked`, `latestRunStatus`, and `latestResultCode` directly in the queue row.
- Use `summary.riskLevel`, `summary.summary`, and `summary.recommendedAction` for explainable trust queue/drawer copy.
- Use `owner` directly in the queue row for assigned investigations.
- Use `GET /api/v1/trust/transcripts/{transcriptId}/details` for the trust details panel.
- Use `POST /api/v1/trust/transcripts/{transcriptId}/block` when the reviewer wants to explicitly stop progression.
- Use `POST /api/v1/trust/transcripts/{transcriptId}/unblock` when the reviewer wants to clear that trust hold.
- Use `POST /api/v1/trust/transcripts/{transcriptId}/assign` when the reviewer assigns the case.
- Use `POST /api/v1/trust/transcripts/{transcriptId}/resolve` when the reviewer clears the case.
- Use `POST /api/v1/trust/transcripts/{transcriptId}/escalate` when the reviewer pushes the case to deeper review.
- Prefer `latestRun.result` for the top-level trust outcome.
- Prefer `actions[n].result` for step-level trust history.
- Useful trust result codes currently include:
  - `trust_case_blocked`
  - `trust_case_unblocked`
  - `trust_document_quarantined`
  - `trust_document_released`
  - `trust_case_assigned`
  - `trust_case_resolved`
  - `trust_case_escalated`
  - `document_match_confirmed`
  - `document_match_rejected`

## Today’s Work Contract

The first orchestrator-facing surface is read-only. It reuses projected work state and overlays the latest document, trust, and decision agent outcomes per student.

Backend note: `OrchestratorAgent` now has explicit backend input/output schemas for projected work items, grouped queue outputs, and normalized `today_work_prioritized` results. It also exposes projected work queue, ownership, and priority backend tools. No frontend request/response changes are required for this scaffold slice.

### Load Today’s Work

- Method: `GET`
- URL: `/api/v1/work/today`
- Query params:
  - `limit=<1..100>`

Example response:

```json
{
  "items": [
    {
      "id": "work_123",
      "studentId": "student-1",
      "studentName": "Mira Holloway",
      "section": "ready",
      "priority": "urgent",
      "priorityScore": 88,
      "owner": {
        "id": "usr_42",
        "name": "Elian Brooks"
      },
      "reasonToAct": {
        "code": "ready_for_decision",
        "label": "Ready for decision"
      },
      "suggestedAction": {
        "code": "review_recommendation",
        "label": "Review recommendation"
      },
      "currentOwnerAgent": "decision_agent",
      "currentStage": "recommendation_ready",
      "recommendedAgent": "decision_agent",
      "queueGroup": "decision_review",
      "documentAgent": {
        "runId": "run-doc-1",
        "status": "completed",
        "resultCode": "transcript_processed",
        "updatedAt": "2026-05-05T18:11:18Z"
      },
      "trustAgent": {
        "runId": "run-trust-1",
        "status": "completed",
        "resultCode": "trust_case_resolved",
        "updatedAt": "2026-05-05T18:12:00Z"
      },
      "decisionAgent": {
        "runId": "run-decision-1",
        "status": "completed",
        "resultCode": "decision_recommendation_generated",
        "updatedAt": "2026-05-05T18:13:00Z"
      },
      "updatedAt": "2026-05-05T18:13:00Z"
    }
  ],
  "total": 1
}
```

### Load Today’s Work Board

- Method: `GET`
- URL: `/api/v1/work/today/board`
- Query params:
  - `limit=<1..100>`

Example response:

```json
{
  "groups": [
    {
      "key": "decision_review",
      "label": "Decision Review",
      "total": 1,
      "routeHint": {
        "nextAgent": "decision_agent",
        "reason": "These students are ready for recommendation or decision review.",
        "actionLabel": "Route to decision review"
      },
      "items": [
        {
          "id": "work_123",
          "studentId": "student-1",
          "studentName": "Mira Holloway",
          "section": "ready",
          "priority": "urgent",
          "priorityScore": 88,
          "owner": {
            "id": "usr_42",
            "name": "Elian Brooks"
          },
          "reasonToAct": {
            "code": "ready_for_decision",
            "label": "Ready for decision"
          },
          "suggestedAction": {
            "code": "review_recommendation",
            "label": "Review recommendation"
          },
          "currentOwnerAgent": "document_agent",
          "currentStage": "routed",
          "recommendedAgent": "decision_agent",
          "queueGroup": "decision_review",
          "updatedAt": "2026-05-05T18:13:00Z"
        }
      ]
    }
  ],
  "total": 1
}
```

### Recommended Today’s Work Behavior

- Use `GET /api/v1/work/today` for a compact orchestrator-style list of priority work.
- Use `GET /api/v1/work/today/board` when the UI needs backend-grouped review buckets instead of one flat list.
- Treat this as a read-only aggregation over existing work and agent surfaces.
- Use `currentOwnerAgent` and `currentStage` as hints for which subsystem currently owns the student’s flow.
- Use `recommendedAgent`, `queueGroup`, and `priorityScore` for backend-owned routing and ordering hints.
- Use `groups[n].routeHint` when the UI wants a single backend-recommended next owner for the whole bucket.
- Use `documentAgent.resultCode`, `trustAgent.resultCode`, and `decisionAgent.resultCode` for quick status chips or routing cues.
- Keep using `GET /api/v1/work/items` when the UI needs the fuller checklist-heavy queue rows.

### Recommend Today’s Work Route

- Method: `GET`
- URL: `/api/v1/work/today/{studentId}/recommendation`

Example response:

```json
{
  "studentId": "student-1",
  "recommendedAgent": "decision_agent",
  "currentOwnerAgent": "document_agent",
  "currentStage": "routed",
  "reason": "The student is ready for decision review, so decision handling should own the next step."
}
```

### Orchestrate Today’s Work

- Method: `POST`
- URL: `/api/v1/work/today/orchestrate`
- Query params:
  - `limit=<1..100>`

Example response:

```json
{
  "agentRunId": "run-orch-1",
  "board": {
    "groups": [
      {
        "key": "decision_review",
        "label": "Decision Review",
        "total": 1,
        "routeHint": {
          "nextAgent": "decision_agent",
          "reason": "These students are ready for recommendation or decision review.",
          "actionLabel": "Route to decision review"
        },
        "items": [
          {
            "id": "work_123",
            "studentId": "student-1",
            "studentName": "Mira Holloway",
            "section": "ready",
            "priority": "urgent",
            "priorityScore": 88,
            "owner": {
              "id": "usr_42",
              "name": "Elian Brooks"
            },
            "reasonToAct": {
              "code": "ready_for_decision",
              "label": "Ready for decision"
            },
            "suggestedAction": {
              "code": "review_recommendation",
              "label": "Review recommendation"
            },
            "recommendedAgent": "decision_agent",
            "queueGroup": "decision_review",
            "updatedAt": "2026-05-05T18:13:00Z"
          }
        ]
      }
    ],
    "total": 1
  },
  "run": {
    "runId": "run-orch-1",
    "agentName": "orchestrator_agent",
    "agentType": "orchestrator",
    "status": "completed",
    "triggerEvent": "manual_today_work_orchestration",
    "result": {
      "status": "completed",
      "code": "today_work_prioritized",
      "message": "Today's work prioritized and grouped.",
      "error": null,
      "metrics": {
        "totalStudents": 1,
        "groupCount": 1
      },
      "artifacts": {
        "groupKeys": [
          "decision_review"
        ]
      }
    }
  },
  "actions": [
    {
      "actionId": "action-orch-1",
      "actionType": "prioritize_today_work_group",
      "toolName": "prioritize_today_work_group",
      "status": "completed",
      "result": {
        "status": "completed",
        "code": "today_work_group_prioritized",
        "message": "Decision Review queue grouped.",
        "error": null,
        "metrics": {
          "groupTotal": 1
        },
        "artifacts": {
          "groupKey": "decision_review",
          "studentIds": [
            "student-1"
          ],
          "routeHint": {
            "nextAgent": "decision_agent",
            "reason": "These students are ready for recommendation or decision review.",
            "actionLabel": "Route to decision review"
          ]
        }
      }
    }
  ]
}
```

### Load Latest Today’s Work Orchestration

- Method: `GET`
- URL: `/api/v1/work/today/orchestrations/latest`
- Query params:
  - `studentId=<optional student id>`

Example response:

```json
{
  "agentRunId": "run-orch-1",
  "board": {
    "groups": [
      {
        "key": "decision_review",
        "label": "Decision Review",
        "total": 1,
        "routeHint": {
          "nextAgent": "decision_agent",
          "reason": "These students are ready for recommendation or decision review.",
          "actionLabel": "Route to decision review"
        },
        "items": [
          {
            "id": "work_123",
            "studentId": "student-1",
            "studentName": "Mira Holloway",
            "section": "ready",
            "priority": "urgent",
            "priorityScore": 88,
            "recommendedAgent": "decision_agent",
            "queueGroup": "decision_review",
            "updatedAt": "2026-05-05T18:13:00Z"
          }
        ]
      }
    ],
    "total": 1
  },
  "run": {
    "runId": "run-orch-1",
    "agentName": "orchestrator_agent",
    "agentType": "orchestrator",
    "status": "completed",
    "triggerEvent": "manual_today_work_orchestration",
    "result": {
      "status": "completed",
      "code": "today_work_prioritized",
      "message": "Today's work prioritized and grouped.",
      "error": null,
      "metrics": {
        "totalStudents": 1,
        "groupCount": 1
      },
      "artifacts": {
        "groupKeys": [
          "decision_review"
        ]
      }
    }
  },
  "actions": []
}
```

### Route Today’s Work

- Method: `POST`
- URL: `/api/v1/work/today/{studentId}/route`
- Body:

```json
{
  "nextAgent": "decision_agent",
  "note": "Ready for recommendation review."
}
```

Valid `nextAgent` values right now:

- `document_agent`
- `trust_agent`
- `decision_agent`

Example response:

```json
{
  "studentId": "student-1",
  "nextAgent": "decision_agent",
  "currentStage": "routed",
  "detail": "Work item routed to decision_agent."
}
```

### Recommended Route Behavior

- Use `GET /api/v1/work/today/{studentId}/recommendation` when the UI wants a backend-owned suggestion for `nextAgent` before routing.
- Use `POST /api/v1/work/today/orchestrate` when the UI wants a persisted orchestrator run explaining the current grouped queue.
- Use `GET /api/v1/work/today/orchestrations/latest` when the UI needs to reopen the latest persisted orchestrator snapshot for the tenant or for one student.
- Use `POST /api/v1/work/today/{studentId}/route` when the UI wants to explicitly hand a student’s next step to one subsystem.
- Treat this as a queue routing hint and ownership update, not as direct execution of the destination agent.
- Prefer the recommendation response over frontend-only heuristics when choosing the destination agent.
- Use `run.result` as the top-level orchestration summary and `actions[n].result` for per-group prioritization details.
- Prefer `board.groups[n].routeHint` for bucket-level routing controls and `actions[n].result.artifacts.routeHint` when reopening persisted prioritization decisions.
- After routing, refresh `GET /api/v1/work/today` so `currentOwnerAgent` and `currentStage` stay in sync.
- Useful orchestrator tool result codes currently include:
  - `projected_work_queue_loaded`
  - `work_ownership_loaded`
  - `work_priority_loaded`
  - `today_work_prioritized`
  - `today_work_group_prioritized`

## Work Projection Contract

The work queue now reads from `student_work_state` projection data instead of recalculating the whole tenant on every read. For tenant warm-up or deploy-time prewarming, use these endpoints.

Read-time work endpoints no longer perform a hidden tenant-wide projection rebuild when projection rows are missing. Projection updates are write-side/event-driven for single-student changes, or explicit through the rebuild endpoints below.

Post-rollout profiling moved `/api/v1/work/items` filtering, counts, limit, and offset onto the projected `student_work_state` query instead of filtering the full projected tenant in application memory.

### Get Work Projection Status

- Method: `GET`
- URL: `/api/v1/work/projection/status`

Example response:

```json
{
  "projectedStudents": 129,
  "totalStudents": 129,
  "ready": true,
  "lastProjectedAt": "2026-05-05T18:11:18Z",
  "remainingStudents": 0,
  "nextCursor": null,
  "currentJob": {
    "jobId": "8a9a9b5d-8d63-4fd0-85a0-a1e5cb9b3578",
    "status": "completed",
    "resetRequested": true,
    "chunkSize": 100,
    "processedStudents": 129,
    "remainingStudents": 0,
    "nextCursor": null,
    "error": null,
    "startedAt": "2026-05-05T18:10:00Z",
    "completedAt": "2026-05-05T18:11:18Z"
  }
}
```

`currentJob.status` can be:

- `queued`
- `running`
- `completed`
- `failed`

### Rebuild One Projection Chunk

- Method: `POST`
- URL: `/api/v1/work/projection/rebuild`
- Query params:
  - `reset=true|false`
  - `limit=<1..500>`
  - `cursor=<optional nextCursor>`

Example response:

```json
{
  "status": "partial",
  "detail": "Work-state projection rebuild chunk completed.",
  "processedStudents": 25,
  "nextCursor": "1d34d2c6-8074-4d7d-8ba1-3a13fe441a11",
  "remainingStudents": 104
}
```

### Rebuild Full Projection

- Method: `POST`
- URL: `/api/v1/work/projection/rebuild-all`
- Query params:
  - `reset=true|false`
  - `limit=<1..500>`

Example response:

```json
{
  "status": "queued",
  "detail": "Full work-state projection rebuild queued.",
  "jobId": "8a9a9b5d-8d63-4fd0-85a0-a1e5cb9b3578",
  "processedStudents": 0,
  "nextCursor": null,
  "remainingStudents": 0
}
```

After calling `rebuild-all`, poll `GET /api/v1/work/projection/status` until:

- `ready == true`
- and `currentJob.status == "completed"`

If `currentJob.status == "failed"`, surface `currentJob.error` in admin/ops UI.

### List Projection Jobs

- Method: `GET`
- URL: `/api/v1/work/projection/jobs`
- Query params:
  - `limit=<1..100>`

Example response:

```json
{
  "items": [
    {
      "jobId": "8a9a9b5d-8d63-4fd0-85a0-a1e5cb9b3578",
      "status": "failed",
      "resetRequested": true,
      "chunkSize": 100,
      "processedStudents": 50,
      "remainingStudents": 79,
      "nextCursor": "1d34d2c6-8074-4d7d-8ba1-3a13fe441a11",
      "error": "database timeout while rebuilding projection",
      "startedAt": "2026-05-05T18:10:00Z",
      "completedAt": "2026-05-05T18:12:00Z",
      "createdAt": "2026-05-05T18:09:55Z",
      "updatedAt": "2026-05-05T18:12:00Z"
    }
  ]
}
```

### Get Projection Job

- Method: `GET`
- URL: `/api/v1/work/projection/jobs/{jobId}`

Use this when the admin/ops UI needs one stable record for a job details panel or a failed-job banner.

### Retry Projection Job

- Method: `POST`
- URL: `/api/v1/work/projection/jobs/{jobId}/retry`

Example response:

```json
{
  "status": "queued",
  "detail": "Projection job retry queued.",
  "jobId": "5af55536-e70f-4748-bf61-216674b1ab5b",
  "processedStudents": 0,
  "nextCursor": null,
  "remainingStudents": 0
}
```

Retry creates a new job with the same `resetRequested` and `chunkSize` values as the failed or prior job. After calling retry:

- poll `GET /api/v1/work/projection/status`
- or poll `GET /api/v1/work/projection/jobs/{jobId}` using the returned `jobId`

### Cancel Projection Job

- Method: `POST`
- URL: `/api/v1/work/projection/jobs/{jobId}/cancel`

Example response:

```json
{
  "jobId": "8a9a9b5d-8d63-4fd0-85a0-a1e5cb9b3578",
  "status": "canceled",
  "resetRequested": true,
  "chunkSize": 100,
  "processedStudents": 50,
  "remainingStudents": 79,
  "nextCursor": "1d34d2c6-8074-4d7d-8ba1-3a13fe441a11",
  "error": null,
  "startedAt": "2026-05-05T18:10:00Z",
  "completedAt": "2026-05-05T18:12:00Z",
  "createdAt": "2026-05-05T18:09:55Z",
  "updatedAt": "2026-05-05T18:12:00Z"
}
```

Cancellation is best-effort. The backend marks the job `canceled` and the running loop stops before the next projection chunk starts.

## Recommended Work Projection Behavior

- For tenant warm-up, prefer `POST /api/v1/work/projection/rebuild-all?reset=true&limit=100`.
- Poll `GET /api/v1/work/projection/status` every 2 to 5 seconds while the admin/ops panel is open.
- If `currentJob.status == "failed"`, show `currentJob.error` and offer a retry action.
- If `currentJob.status == "running"`, optionally offer a cancel action through `POST /api/v1/work/projection/jobs/{jobId}/cancel`.
- For a projection history table, use `GET /api/v1/work/projection/jobs`.
- For a failed-job details drawer, use `GET /api/v1/work/projection/jobs/{jobId}`.
- When the user clicks retry, call `POST /api/v1/work/projection/jobs/{jobId}/retry`, store the returned `jobId`, then refresh `status` and the jobs list.

## Lifecycle Contract

The first `lifecycle_agent` slice is backend-only. It defines normalized admit-to-deposit lifecycle inputs, recommendation outputs, and tool result envelopes for future lifecycle runs. No frontend request/response changes are required yet; continue to use the existing student, dashboard, and melt queue APIs for visible lifecycle and yield work.

Useful lifecycle result codes currently include:

- `admit_to_deposit_cohort_loaded`
- `deposit_likelihood_scored`
- `melt_risk_scored`
- `lifecycle_intervention_logged`
- `lifecycle_outreach_logged`
- `lifecycle_recommendations_generated`

### Recommended Lifecycle Behavior

- Continue to use existing student 360 fields such as `depositLikelihood`, `risk`, `stage`, `nextBestAction`, and transcript summary fields for current UI.
- Continue to use the existing melt queue endpoint for operational melt-review lists.
- Treat lifecycle tool outputs as backend agent-run artifacts until a public lifecycle endpoint is added.
- When lifecycle agent details are eventually exposed, prefer `run.result` for the top-level recommendation summary and `actions[n].result` for cohort, scoring, intervention, and outreach steps.
