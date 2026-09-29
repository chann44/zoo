#import <Virtualization/Virtualization.h>

// Starts Virtualization.framework's built-in VNC server for a VM. Returns nil if the
// private classes are unavailable on this macOS version.
id _Nullable ZooVNCStart(VZVirtualMachine * _Nonnull vm, NSString * _Nonnull password);
NSInteger ZooVNCPort(id _Nonnull server);
