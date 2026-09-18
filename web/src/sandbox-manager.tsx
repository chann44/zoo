import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const API_URL = "http://localhost:8000";

type Sandbox = {
  id: string;
  container_id: string;
  container_name: string;
  host_port: number;
};

export default function SandboxManager() {
  const [sandboxes, setSandboxes] =
    useState<Sandbox[]>([]);

  const [creating, setCreating] =
    useState(false);

  const [deleting, setDeleting] =
    useState<string | null>(null);

  const [error, setError] =
    useState<string | null>(null);

  async function createSandbox() {
    try {
      setCreating(true);
      setError(null);

      const response = await fetch(
        `${API_URL}/sandboxes`,
        {
          method: "POST",
        }
      );

      if (!response.ok) {
        throw new Error(
          "Failed to create sandbox"
        );
      }

      const sandbox: Sandbox =
        await response.json();

      setSandboxes((current) => [
        ...current,
        sandbox,
      ]);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Something went wrong"
      );
    } finally {
      setCreating(false);
    }
  }

  async function deleteSandbox(
    sandboxId: string
  ) {
    try {
      setDeleting(sandboxId);
      setError(null);

      const response = await fetch(
        `${API_URL}/sandboxes/${sandboxId}`,
        {
          method: "DELETE",
        }
      );

      if (!response.ok) {
        throw new Error(
          "Failed to delete sandbox"
        );
      }

      setSandboxes((current) =>
        current.filter(
          (sandbox) =>
            sandbox.id !== sandboxId
        )
      );
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Something went wrong"
      );
    } finally {
      setDeleting(null);
    }
  }

  return (
    <main className="mx-auto max-w-3xl p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">
            Sandboxes
          </h1>

          <p className="text-sm text-gray-500">
            Agent environments
          </p>
        </div>

        <button
          onClick={createSandbox}
          disabled={creating}
          className="rounded-lg bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {creating
            ? "Creating..."
            : "Create Sandbox"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-600">
          {error}
        </div>
      )}

      <div className="space-y-3">
        {sandboxes.length === 0 && (
          <div className="rounded-lg border p-8 text-center text-sm text-gray-500">
            No sandboxes.
          </div>
        )}

        {sandboxes.map((sandbox) => (
          <div
            key={sandbox.id}
            className="flex items-center justify-between rounded-lg border p-4"
          >
            <div>
              <p className="font-medium">
                {sandbox.container_name}
              </p>

              <p className="text-xs text-gray-500">
                {sandbox.id}
              </p>
            </div>

            <div className="flex gap-2">
              <Link
                to={`/sandboxes/${sandbox.id}`}
                className="rounded-lg border px-3 py-2 text-sm"
              >
                Open
              </Link>

              <button
                onClick={() =>
                  deleteSandbox(sandbox.id)
                }
                disabled={
                  deleting === sandbox.id
                }
                className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600 disabled:opacity-50"
              >
                {deleting === sandbox.id
                  ? "Deleting..."
                  : "Delete"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}