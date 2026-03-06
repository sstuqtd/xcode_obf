#import <Foundation/Foundation.h>

@interface Helper : NSObject
- (void)initConfig;
- (void)cleanup;
@end

@implementation Helper
- (void)initConfig
{
    NSLog(@"cfg 1");
    NSLog(@"cfg 2");
    NSLog(@"cfg 3");
    NSLog(@"cfg 4");
    NSLog(@"cfg 5");
}
- (void)cleanup
{
    NSLog(@"clean 1");
    NSLog(@"clean 2");
    NSLog(@"clean 3");
}
@end
