import Foundation
import ApplicationServices
import AppKit


/*
    Memory 시스템 https://arxiv.org/pdf/2603.03596 비슷하게.

현재 Open-TARS는 move가 사실상 단일동작에 정적이며, 실제 유기적인 move, scroll에 대해서 모델이 이해하지 못함.
이전에 촬영되었던 화면의 해상도를 열화 하고 마우스 움직임을 선으로 나타내어 텍스트 형태의 메모리로 저장하여 이전에 하였던것들을 기록하여 모델이 과거에 하였던 일들에 대해서 text 형태로 longterm memory 유지,
또한, 검증 또는 확인과정에서 모델이 화면의 변화를 인지하도록 특정 역할에게는 이전 프레임과 현재 프레임의 차이를 어찌저찌 알고리즘으로 조작해서 모델에게 제공하여, 버튼 눌렸는지 또는 마우스 이동 등을 인지하도록.

*/

class CGMemory {

    init(parameters) {
        statements
    }
}