{{/*
Expand the name of the chart.
*/}}
{{- define "resource-right-sizing.name" -}}
{{- printf "%s-%s" .Values.nameOverride .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "resource-right-sizing.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" $name .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "resource-right-sizing.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "resource-right-sizing.labels" -}}
helm.sh/chart: {{ include "resource-right-sizing.chart" . }}
{{ include "resource-right-sizing.selectorLabels" . }}
{{- if .Values.tag_version }}
app.kubernetes.io/version: {{ .Values.tag_version | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}


{{/*
Selector labels
*/}}
{{- define "resource-right-sizing.selectorLabels" -}}
app.kubernetes.io/name: {{ include "resource-right-sizing.name" . }}
app.kubernetes.io/app: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "resource-right-sizing.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "resource-right-sizing.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}


{{- define "helpers.list-env-variables"}}
{{- $SecretName := include "resource-right-sizing.fullname" . -}}
{{- range $key, $val := .Values.resource_sizing.secrets }}
    - name: {{ $key }}
      valueFrom:
        secretKeyRef:
          name: {{ $SecretName }}-secrets
          key: {{ $key }}
{{- end}}
{{- range $key, $val := .Values.resource_sizing.plain }}
    - name: {{ $key }}
      value: {{ $val | quote }}
{{- end}}
{{- end }}
