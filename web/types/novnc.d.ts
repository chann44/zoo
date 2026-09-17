declare module "@novnc/novnc" {
  export default class RFB {
    constructor(target: HTMLElement, url: string, options?: Record<string, unknown>);
    scaleViewport: boolean;
    resizeSession: boolean;
    disconnect(): void;
    addEventListener(event: string, handler: (e: any) => void): void;
  }
}