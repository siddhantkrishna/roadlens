// AVFoundation owns device discovery and capture; Python owns all vision processing.
#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <CoreVideo/CoreVideo.h>
#import <arpa/inet.h>
#import <signal.h>
#import <unistd.h>

static NSArray<AVCaptureDevice *> *devices(void) {
    NSMutableArray *types = [NSMutableArray arrayWithObject:AVCaptureDeviceTypeBuiltInWideAngleCamera];
    if (@available(macOS 14.0, *)) {
        [types addObject:AVCaptureDeviceTypeExternal];
        [types addObject:AVCaptureDeviceTypeContinuityCamera];
    } else {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        [types addObject:AVCaptureDeviceTypeExternalUnknown];
#pragma clang diagnostic pop
    }
    return [AVCaptureDeviceDiscoverySession discoverySessionWithDeviceTypes:types
        mediaType:AVMediaTypeVideo position:AVCaptureDevicePositionUnspecified].devices;
}

static BOOL permission(void) {
    AVAuthorizationStatus status = [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
    if (status == AVAuthorizationStatusAuthorized) return YES;
    if (status != AVAuthorizationStatusNotDetermined) return NO;
    __block BOOL finished = NO, granted = NO;
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL ok) {
        dispatch_async(dispatch_get_main_queue(), ^{ granted = ok; finished = YES; });
    }];
    while (!finished) [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    return granted;
}

static BOOL writeAll(const void *bytes, size_t count) {
    const uint8_t *cursor = bytes;
    while (count) {
        ssize_t sent = write(STDOUT_FILENO, cursor, count);
        if (sent < 0 && errno == EINTR) continue;
        if (sent <= 0) return NO;
        cursor += sent; count -= sent;
    }
    return YES;
}

@interface FrameOutput : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate>
@end
@implementation FrameOutput
- (void)captureOutput:(AVCaptureOutput *)output didOutputSampleBuffer:(CMSampleBufferRef)sample
       fromConnection:(AVCaptureConnection *)connection {
    @autoreleasepool {
        CVPixelBufferRef pixel = CMSampleBufferGetImageBuffer(sample);
        if (!pixel || CVPixelBufferLockBaseAddress(pixel, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess) return;
        size_t w = CVPixelBufferGetWidth(pixel), h = CVPixelBufferGetHeight(pixel);
        size_t stride = CVPixelBufferGetBytesPerRow(pixel);
        const uint8_t *base = CVPixelBufferGetBaseAddress(pixel);
        if (!base || w > 3840 || h > 2160 || stride < w * 4) {
            CVPixelBufferUnlockBaseAddress(pixel, kCVPixelBufferLock_ReadOnly); return;
        }
        // Copy before unlocking: AVFoundation recycles this memory after the callback.
        NSMutableData *data = [NSMutableData dataWithLength:w * h * 4];
        for (size_t y = 0; y < h; y++) memcpy((uint8_t *)data.mutableBytes + y*w*4, base+y*stride, w*4);
        CVPixelBufferUnlockBaseAddress(pixel, kCVPixelBufferLock_ReadOnly);
        uint32_t header[] = {htonl(0x524c3031), htonl((uint32_t)w), htonl((uint32_t)h), htonl((uint32_t)data.length)};
        if (!writeAll(header, sizeof(header)) || !writeAll(data.bytes, data.length)) _exit(0);
    }
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        signal(SIGPIPE, SIG_IGN);
        if (argc == 2 && strcmp(argv[1], "list") == 0) {
            NSMutableArray *result = [NSMutableArray array];
            for (AVCaptureDevice *device in devices()) {
                [result addObject:@{@"id": device.uniqueID, @"name": device.localizedName,
                                    @"type": device.deviceType}];
            }
            NSData *json = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
            writeAll(json.bytes, json.length); return 0;
        }
        if (argc != 6 || strcmp(argv[1], "capture") != 0) {
            fprintf(stderr, "usage: roadlens-camera list | capture DEVICE_ID WIDTH HEIGHT FPS\n"); return 2;
        }
        int width = atoi(argv[3]), height = atoi(argv[4]), fps = atoi(argv[5]);
        if (width <= 0 || width > 3840 || height <= 0 || height > 2160 || fps <= 0 || fps > 120) return 2;
        if (!permission()) {
            fprintf(stderr, "Camera permission denied. Enable ROADLENS Camera or your terminal in System Settings > Privacy & Security > Camera.\n");
            return 3;
        }
        AVCaptureDevice *device = nil;
        NSString *uid = [NSString stringWithUTF8String:argv[2]];
        for (AVCaptureDevice *candidate in devices()) if ([candidate.uniqueID isEqualToString:uid]) device = candidate;
        if (!device) { fprintf(stderr, "Selected camera is unavailable\n"); return 4; }
        NSError *error = nil;
        AVCaptureDeviceInput *input = [AVCaptureDeviceInput deviceInputWithDevice:device error:&error];
        if (!input) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 5; }
        AVCaptureSession *session = [AVCaptureSession new];
        [session beginConfiguration];
        NSString *preset = width <= 640 && height <= 480 ? AVCaptureSessionPreset640x480 :
                           width <= 1280 && height <= 720 ? AVCaptureSessionPreset1280x720 : AVCaptureSessionPreset1920x1080;
        if ([session canSetSessionPreset:preset]) session.sessionPreset = preset;
        if (![session canAddInput:input]) { fprintf(stderr, "Cannot add camera input\n"); return 5; }
        [session addInput:input];
        AVCaptureVideoDataOutput *output = [AVCaptureVideoDataOutput new];
        output.alwaysDiscardsLateVideoFrames = YES;
        output.videoSettings = @{(id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA)};
        // The output does not retain its delegate; keep it alive through the run loop.
        __attribute__((objc_precise_lifetime)) FrameOutput *delegate = [FrameOutput new];
        dispatch_queue_t queue = dispatch_queue_create("local.roadlens.frames", DISPATCH_QUEUE_SERIAL);
        [output setSampleBufferDelegate:delegate queue:queue];
        if (![session canAddOutput:output]) { fprintf(stderr, "Cannot add camera output\n"); return 5; }
        [session addOutput:output];
        [session commitConfiguration];
        if ([device lockForConfiguration:&error]) {
            for (AVFrameRateRange *range in device.activeFormat.videoSupportedFrameRateRanges) {
                if (range.minFrameRate <= fps && fps <= range.maxFrameRate) {
                    device.activeVideoMinFrameDuration = CMTimeMake(1, fps);
                    device.activeVideoMaxFrameDuration = CMTimeMake(1, fps); break;
                }
            }
            [device unlockForConfiguration];
        }
        __block BOOL failed = NO;
        id observer = [[NSNotificationCenter defaultCenter] addObserverForName:AVCaptureSessionRuntimeErrorNotification
            object:session queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification *note) {
                fprintf(stderr, "Capture session error: %s\n", [note.userInfo description].UTF8String); failed = YES;
            }];
        [session startRunning];
        while (session.isRunning && device.isConnected && !failed)
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        [session stopRunning];
        [[NSNotificationCenter defaultCenter] removeObserver:observer];
        return 6;
    }
}
