# Evaluation Workspace

This directory stores generated screening, coding, pooling, and evaluation
outputs. Only this README is versioned; run outputs must not be committed.

Recommended layout:

```text
evaluation/<disease>/screening/<parameter>/p<id>/
evaluation/<disease>/coding/<parameter>/p<id>/
```

Use unique run or experiment subdirectories when comparing prompts or models.
Fixed inputs belong under `dataset/`, not here.
