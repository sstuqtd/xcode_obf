#import <Foundation/Foundation.h>

@interface Foo : NSObject
- (void)processData;
@end

@implementation Foo
- (void)processData
{
    NSLog(@"step 1");
    NSLog(@"step 2");
    NSLog(@"step 3");
    NSLog(@"step 4");
    NSLog(@"step 5");
}
@end
