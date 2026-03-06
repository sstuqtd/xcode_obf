#import <Foundation/Foundation.h>

@interface Bar : NSObject
- (void)handleResponse:(id)response task:(id)task;
- (void)setupUI;
@end

@implementation Bar
- (void)handleResponse:(id)response task:(id)task
{
    int x = 1;
    int y = 2;
    NSLog(@"response %@", response);
}
- (void)setupUI
{
    NSLog(@"init");
    NSLog(@"config");
    NSLog(@"layout");
    NSLog(@"done");
}
@end
