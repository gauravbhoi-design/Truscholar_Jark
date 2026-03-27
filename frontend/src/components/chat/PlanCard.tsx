"use client";

import { useState } from "react";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Play,
  SkipForward,
  ThumbsUp,
  ThumbsDown,
  Wrench,
  ChevronDown,
  ChevronRight,
  AlertCircle,
  Clock,
  Shield,
} from "lucide-react";
import {
  approvePlan,
  executePlanStep,
  type PlanResponse,
  type PlanStep,
} from "@/lib/api";

interface PlanCardProps {
  plan: PlanResponse;
  onUpdate: (plan: PlanResponse) => void;
}

const STEP_STATUS_CONFIG = {
  pending: { icon: Clock, color: "text-muted-foreground", bg: "bg-muted", label: "Pending" },
  approved: { icon: ThumbsUp, color: "text-blue-500", bg: "bg-blue-500/10", label: "Approved" },
  executing: { icon: Loader2, color: "text-yellow-500", bg: "bg-yellow-500/10", label: "Running" },
  completed: { icon: CheckCircle2, color: "text-green-500", bg: "bg-green-500/10", label: "Done" },
  failed: { icon: XCircle, color: "text-red-500", bg: "bg-red-500/10", label: "Failed" },
  skipped: { icon: SkipForward, color: "text-muted-foreground", bg: "bg-muted", label: "Skipped" },
};

function StepRow({
  step,
  planId,
  planStatus,
  onStepUpdate,
}: {
  step: PlanStep;
  planId: string;
  planStatus: string;
  onStepUpdate: (stepId: string, updates: Partial<PlanStep>) => void;
}) {
  const [executing, setExecuting] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const cfg = STEP_STATUS_CONFIG[step.status];
  const StatusIcon = cfg.icon;

  const handleApproveStep = async () => {
    await approvePlan(planId, "approve_step", step.id);
    onStepUpdate(step.id, { status: "approved" });
  };

  const handleSkipStep = async () => {
    await approvePlan(planId, "skip_step", step.id);
    onStepUpdate(step.id, { status: "skipped" });
  };

  const handleExecuteStep = async () => {
    setExecuting(true);
    onStepUpdate(step.id, { status: "executing" });
    try {
      const result = await executePlanStep(planId, step.id);
      onStepUpdate(step.id, {
        status: (result.status as PlanStep["status"]) || "completed",
        result: result.result as Record<string, unknown>,
      });
    } catch {
      onStepUpdate(step.id, { status: "failed" });
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className={`border rounded-md overflow-hidden ${step.status === "executing" ? "ring-1 ring-yellow-500/30" : ""}`}>
      <div className="flex items-center gap-3 px-3 py-2.5">
        {/* Step number */}
        <span className="text-xs font-mono text-muted-foreground w-5 shrink-0">{step.order}</span>

        {/* Status badge */}
        <span className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full shrink-0 ${cfg.bg} ${cfg.color}`}>
          <StatusIcon className={`h-3 w-3 ${step.status === "executing" ? "animate-spin" : ""}`} />
          {cfg.label}
        </span>

        {/* Title & description */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex-1 text-left flex items-center gap-1 min-w-0"
        >
          {expanded ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />}
          <span className="text-sm font-medium truncate">{step.title}</span>
        </button>

        {/* Tool badge */}
        <code className="text-[10px] px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground shrink-0">
          {step.tool_name}
        </code>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          {step.status === "pending" && planStatus !== "rejected" && (
            <>
              <button
                onClick={handleApproveStep}
                className="p-1 rounded hover:bg-green-500/10 text-green-500"
                title="Approve step"
              >
                <ThumbsUp className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={handleSkipStep}
                className="p-1 rounded hover:bg-muted text-muted-foreground"
                title="Skip step"
              >
                <SkipForward className="h-3.5 w-3.5" />
              </button>
            </>
          )}
          {step.status === "approved" && (
            <button
              onClick={handleExecuteStep}
              disabled={executing}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {executing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              Run
            </button>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-3 pb-2.5 pt-0 border-t bg-muted/20">
          <p className="text-xs text-muted-foreground mt-2">{step.description}</p>
          <div className="mt-2">
            <p className="text-[10px] font-medium text-muted-foreground mb-1">Tool Input:</p>
            <pre className="text-[10px] bg-background rounded p-2 overflow-x-auto max-h-24">
              {JSON.stringify(step.tool_input, null, 2)}
            </pre>
          </div>
          {step.result && (
            <div className="mt-2">
              <p className="text-[10px] font-medium text-muted-foreground mb-1">Result:</p>
              <pre className="text-[10px] bg-background rounded p-2 overflow-x-auto max-h-32">
                {JSON.stringify(step.result, null, 2).slice(0, 500)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function PlanCard({ plan: initialPlan, onUpdate }: PlanCardProps) {
  const [plan, setPlan] = useState(initialPlan);
  const [approving, setApproving] = useState(false);
  const [executingAll, setExecutingAll] = useState(false);

  const updateStep = (stepId: string, updates: Partial<PlanStep>) => {
    setPlan((prev) => {
      const updated = {
        ...prev,
        steps: prev.steps.map((s) => (s.id === stepId ? { ...s, ...updates } : s)),
      };
      onUpdate(updated);
      return updated;
    });
  };

  const handleApproveAll = async () => {
    setApproving(true);
    try {
      await approvePlan(plan.id, "approve_all");
      setPlan((prev) => {
        const updated = {
          ...prev,
          status: "approved" as const,
          steps: prev.steps.map((s) => (s.status === "pending" ? { ...s, status: "approved" as const } : s)),
        };
        onUpdate(updated);
        return updated;
      });
    } finally {
      setApproving(false);
    }
  };

  const handleReject = async () => {
    await approvePlan(plan.id, "reject");
    setPlan((prev) => {
      const updated = { ...prev, status: "rejected" as const };
      onUpdate(updated);
      return updated;
    });
  };

  const handleExecuteAll = async () => {
    setExecutingAll(true);
    // Execute approved steps one by one
    for (const step of plan.steps) {
      if (step.status !== "approved") continue;

      updateStep(step.id, { status: "executing" });
      try {
        const result = await executePlanStep(plan.id, step.id);
        updateStep(step.id, {
          status: (result.status as PlanStep["status"]) || "completed",
          result: result.result as Record<string, unknown>,
        });

        if (result.status === "failed") break; // Stop on failure
      } catch {
        updateStep(step.id, { status: "failed" });
        break;
      }
    }
    setExecutingAll(false);
  };

  const pendingCount = plan.steps.filter((s) => s.status === "pending").length;
  const approvedCount = plan.steps.filter((s) => s.status === "approved").length;
  const completedCount = plan.steps.filter((s) => s.status === "completed").length;

  return (
    <div className="border rounded-lg bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b bg-muted/30">
        <Shield className="h-4 w-4 text-primary" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">Execution Plan</p>
          <p className="text-xs text-muted-foreground truncate">{plan.summary}</p>
        </div>
        <span className="text-xs text-muted-foreground">
          {completedCount}/{plan.steps.length} steps
        </span>
      </div>

      {/* Steps */}
      <div className="p-3 space-y-2">
        {plan.steps.map((step) => (
          <StepRow
            key={step.id}
            step={step}
            planId={plan.id}
            planStatus={plan.status}
            onStepUpdate={updateStep}
          />
        ))}
      </div>

      {/* Actions */}
      {plan.status !== "rejected" && plan.status !== "completed" && (
        <div className="flex items-center gap-2 px-4 py-3 border-t bg-muted/20">
          {pendingCount > 0 && (
            <>
              <button
                onClick={handleApproveAll}
                disabled={approving}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
              >
                {approving ? <Loader2 className="h-3 w-3 animate-spin" /> : <ThumbsUp className="h-3 w-3" />}
                Approve All ({pendingCount})
              </button>
              <button
                onClick={handleReject}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs border border-destructive/30 text-destructive hover:bg-destructive/10"
              >
                <ThumbsDown className="h-3 w-3" />
                Reject
              </button>
            </>
          )}
          {approvedCount > 0 && (
            <button
              onClick={handleExecuteAll}
              disabled={executingAll}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 ml-auto"
            >
              {executingAll ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              Execute All ({approvedCount})
            </button>
          )}
        </div>
      )}

      {plan.status === "rejected" && (
        <div className="flex items-center gap-2 px-4 py-3 border-t bg-destructive/5">
          <AlertCircle className="h-4 w-4 text-destructive" />
          <span className="text-xs text-destructive">Plan rejected — no steps will be executed</span>
        </div>
      )}

      {plan.status === "completed" && (
        <div className="flex items-center gap-2 px-4 py-3 border-t bg-green-500/5">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <span className="text-xs text-green-500">Plan completed — all steps executed</span>
        </div>
      )}
    </div>
  );
}
