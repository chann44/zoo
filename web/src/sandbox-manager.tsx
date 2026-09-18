import { useState } from "react";
import { Link } from "react-router-dom";

const API_URL = "http://localhost:8000";

type Sandbox = {
  id: string;
  container_id: string;
  container_name: string;
  host_port: number;
};

type ClickButton = "left" | "right" | "middle";

export default function SandboxManager() {
  const [sandboxes, setSandboxes] = useState<Sandbox[]>([]);

  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [capturing, setCapturing] = useState<string | null>(null);
  const [clicking, setClicking] = useState<string | null>(null);

  const [screenshots, setScreenshots] = useState<
    Record<string, string>
  >({});

  const [clickX, setClickX] = useState<
    Record<string, string>
  >({});

  const [clickY, setClickY] = useState<
    Record<string, string>
  >({});

  const [clickButton, setClickButton] = useState<
    Record<string, ClickButton>
  >({});

  const [error, setError] = useState<string | null>(null);

  async function createSandbox() {
    try {
      setCreating(true);
      setError(null);

      const response = await fetch(`${API_URL}/sandboxes`, {
        method: "POST",
      });

      if (!response.ok) {
        throw new Error("Failed to create sandbox");
      }

      const sandbox: Sandbox = await response.json();

      setSandboxes((current) => [...current, sandbox]);
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

  async function deleteSandbox(sandboxId: string) {
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
        throw new Error("Failed to delete sandbox");
      }

      setSandboxes((current) =>
        current.filter(
          (sandbox) => sandbox.id !== sandboxId
        )
      );

      setScreenshots((current) => {
        const next = { ...current };

        if (next[sandboxId]) {
          URL.revokeObjectURL(next[sandboxId]);
        }

        delete next[sandboxId];

        return next;
      });

      setClickX((current) => {
        const next = { ...current };
        delete next[sandboxId];
        return next;
      });

      setClickY((current) => {
        const next = { ...current };
        delete next[sandboxId];
        return next;
      });

      setClickButton((current) => {
        const next = { ...current };
        delete next[sandboxId];
        return next;
      });
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

  async function captureScreenshot(sandboxId: string) {
    try {
      setCapturing(sandboxId);
      setError(null);

      const response = await fetch(
        `${API_URL}/sandboxes/${sandboxId}/screenshot`,
        {
          method: "POST",
        }
      );

      if (!response.ok) {
        throw new Error("Failed to capture screenshot");
      }

      const blob = await response.blob();

      const imageUrl = URL.createObjectURL(blob);

      setScreenshots((current) => {
        const previous = current[sandboxId];

        if (previous) {
          URL.revokeObjectURL(previous);
        }

        return {
          ...current,
          [sandboxId]: imageUrl,
        };
      });
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Failed to capture screenshot"
      );
    } finally {
      setCapturing(null);
    }
  }

  async function clickSandbox(sandboxId: string) {
    try {
      setClicking(sandboxId);
      setError(null);

      const x = Number(clickX[sandboxId] ?? 0);
      const y = Number(clickY[sandboxId] ?? 0);
      const button = clickButton[sandboxId] ?? "left";

      if (!Number.isFinite(x) || !Number.isFinite(y)) {
        throw new Error("X and Y coordinates must be valid numbers");
      }

      if (x < 0 || y < 0) {
        throw new Error("X and Y coordinates cannot be negative");
      }

      const response = await fetch(
        `${API_URL}/sandboxes/${sandboxId}/click`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            x,
            y,
            button,
          }),
        }
      );

      if (!response.ok) {
        const errorText = await response.text();

        throw new Error(
          errorText || "Failed to click"
        );
      }

      // Refresh screenshot after click
      await captureScreenshot(sandboxId);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Failed to click"
      );
    } finally {
      setClicking(null);
    }
  }

  return (
    <main className="mx-auto max-w-5xl p-8">
      {/* Header */}
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
          {creating ? "Creating..." : "Create Sandbox"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-600">
          {error}
        </div>
      )}

      {/* Sandboxes */}
      <div className="space-y-6">
        {sandboxes.length === 0 && (
          <div className="rounded-lg border p-8 text-center text-sm text-gray-500">
            No sandboxes.
          </div>
        )}

        {sandboxes.map((sandbox) => {
          const selectedButton =
            clickButton[sandbox.id] ?? "left";

          return (
            <div
              key={sandbox.id}
              className="overflow-hidden rounded-lg border"
            >
              {/* Sandbox header */}
              <div className="flex items-center justify-between p-4">
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
                      captureScreenshot(sandbox.id)
                    }
                    disabled={
                      capturing === sandbox.id
                    }
                    className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
                  >
                    {capturing === sandbox.id
                      ? "Capturing..."
                      : "Screenshot"}
                  </button>

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

              {/* Screenshot */}
              <div className="border-t bg-gray-50 p-4">
                {screenshots[sandbox.id] ? (
                  <div className="overflow-hidden rounded-lg border bg-black">
                    <img
                      src={screenshots[sandbox.id]}
                      alt={`Screenshot of ${sandbox.container_name}`}
                      className="block w-full"
                    />
                  </div>
                ) : (
                  <div className="flex h-64 items-center justify-center rounded-lg border border-dashed bg-white text-sm text-gray-400">
                    No screenshot captured
                  </div>
                )}
              </div>

              {/* Click controls */}
              <div className="border-t p-4">
                <div className="mb-4">
                  <h3 className="text-sm font-medium">
                    Mouse Click
                  </h3>

                  <p className="text-xs text-gray-500">
                    Execute a mouse click inside this
                    sandbox.
                  </p>
                </div>

                <div className="flex items-end gap-3">
                  {/* X */}
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">
                      X
                    </label>

                    <input
                      type="number"
                      min="0"
                      value={clickX[sandbox.id] ?? ""}
                      onChange={(event) =>
                        setClickX((current) => ({
                          ...current,
                          [sandbox.id]:
                            event.target.value,
                        }))
                      }
                      placeholder="100"
                      className="w-24 rounded-lg border px-3 py-2 text-sm outline-none focus:border-black"
                    />
                  </div>

                  {/* Y */}
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">
                      Y
                    </label>

                    <input
                      type="number"
                      min="0"
                      value={clickY[sandbox.id] ?? ""}
                      onChange={(event) =>
                        setClickY((current) => ({
                          ...current,
                          [sandbox.id]:
                            event.target.value,
                        }))
                      }
                      placeholder="200"
                      className="w-24 rounded-lg border px-3 py-2 text-sm outline-none focus:border-black"
                    />
                  </div>

                  {/* Mouse button */}
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">
                      Button
                    </label>

                    <select
                      value={selectedButton}
                      onChange={(event) =>
                        setClickButton((current) => ({
                          ...current,
                          [sandbox.id]:
                            event.target
                              .value as ClickButton,
                        }))
                      }
                      className="rounded-lg border px-3 py-2 text-sm outline-none focus:border-black"
                    >
                      <option value="left">
                        Left
                      </option>

                      <option value="right">
                        Right
                      </option>

                      <option value="middle">
                        Middle
                      </option>
                    </select>
                  </div>

                  {/* Click */}
                  <button
                    onClick={() =>
                      clickSandbox(sandbox.id)
                    }
                    disabled={
                      clicking === sandbox.id
                    }
                    className="rounded-lg bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
                  >
                    {clicking === sandbox.id
                      ? "Clicking..."
                      : "Click"}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </main>
  );
}
