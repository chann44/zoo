#import "VNC.h"

@protocol ZooVNCSecurity
- (instancetype)initWithPassword:(NSString *)password;
@end

@protocol ZooVNCServer
- (instancetype)initWithPort:(NSInteger)port queue:(dispatch_queue_t)queue securityConfiguration:(id)configuration;
- (void)setVirtualMachine:(VZVirtualMachine *)virtualMachine;
- (void)start;
- (NSInteger)port;
@end

id ZooVNCStart(VZVirtualMachine *vm, NSString *password) {
    Class security = NSClassFromString(@"_VZVNCAuthenticationSecurityConfiguration");
    Class server = NSClassFromString(@"_VZVNCServer");
    if (security == nil || server == nil) {
        return nil;
    }
    id configuration = [(id<ZooVNCSecurity>)[security alloc] initWithPassword:password];
    id<ZooVNCServer> vnc = [(id<ZooVNCServer>)[server alloc] initWithPort:0
                                                                    queue:dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0)
                                                    securityConfiguration:configuration];
    [vnc setVirtualMachine:vm];
    [vnc start];
    return vnc;
}

NSInteger ZooVNCPort(id server) {
    return [(id<ZooVNCServer>)server port] & 0xFFFF;
}
